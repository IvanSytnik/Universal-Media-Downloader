"""ReapStaleRequestsUseCase with fakes: the cutoff it asks for, who gets
told what, and that one unreachable user does not stop the batch.

Exactly-once-ness of the transition itself lives in the repository's
compare-and-set (tests/integration/test_stale_request_repository.py);
here the fake hands out each row once, the way the real one does, and
the tests pin that the use case only notifies what it was handed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog

from src.application.use_cases.reap_stale_requests import ReapStaleRequestsUseCase
from src.domain.entities.user import User
from src.domain.exceptions import NotifierError
from src.domain.value_objects.enums import DownloadStatus
from src.domain.value_objects.stale_request import StaleRequest
from tests.conftest import FakeErrorLocalizer

_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
_STALE_AFTER = timedelta(seconds=2400)


class FakeRequestRepository:
    """Hands each queued row out once, like ``fail_stale``'s CAS."""

    def __init__(self, stale: list[StaleRequest]) -> None:
        self._stale = list(stale)
        self.calls: list[tuple[datetime, int]] = []

    async def fail_stale(self, updated_before: datetime, limit: int) -> list[StaleRequest]:
        self.calls.append((updated_before, limit))
        batch, self._stale = self._stale[:limit], self._stale[limit:]
        return batch


class FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self._users = {u.id: u for u in users}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)


class FakeNotifier:
    def __init__(self, failing_ids: frozenset[int] = frozenset()) -> None:
        self._failing_ids = failing_ids
        self.sent_texts: list[tuple[int, str]] = []

    async def send_text(self, telegram_id: int, text: str) -> None:
        if telegram_id in self._failing_ids:
            raise NotifierError("Forbidden: bot was blocked by the user")
        self.sent_texts.append((telegram_id, text))


def _use_case(
    repo: FakeRequestRepository,
    users: list[User],
    notifier: FakeNotifier,
    i18n_core: Any,
    batch_size: int = 100,
) -> ReapStaleRequestsUseCase:
    return ReapStaleRequestsUseCase(
        download_request_repository=repo,  # type: ignore[arg-type]  # partial fake
        user_repository=FakeUserRepository(users),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        error_localizer=FakeErrorLocalizer(i18n_core),
        stale_after=_STALE_AFTER,
        batch_size=batch_size,
        clock=lambda: _NOW,
    )


def _stale(user: User, status: DownloadStatus = DownloadStatus.PROCESSING) -> StaleRequest:
    return StaleRequest(request_id=uuid4(), user_id=user.id, previous_status=status)


@pytest.mark.asyncio
async def test_asks_for_rows_older_than_now_minus_stale_after(i18n_core: Any) -> None:
    repo = FakeRequestRepository([])

    reaped = await _use_case(repo, [], FakeNotifier(), i18n_core, batch_size=7).execute()

    assert reaped == []
    assert repo.calls == [(_NOW - _STALE_AFTER, 7)]


@pytest.mark.asyncio
async def test_notifies_each_reaped_user_in_their_language(i18n_core: Any) -> None:
    ru = User.create_from_telegram(telegram_id=1, language="ru")
    en = User.create_from_telegram(telegram_id=2, language="en")
    rows = [_stale(ru, DownloadStatus.PENDING), _stale(en)]
    notifier = FakeNotifier()
    localizer = FakeErrorLocalizer(i18n_core)

    reaped = await _use_case(FakeRequestRepository(rows), [ru, en], notifier, i18n_core).execute()

    assert reaped == rows
    assert notifier.sent_texts == [
        (1, localizer.localize("error-request-stale", "ru")),
        (2, localizer.localize("error-request-stale", "en")),
    ]
    assert notifier.sent_texts[0][1] != notifier.sent_texts[1][1]


@pytest.mark.asyncio
async def test_logs_request_id_previous_status_and_error_key(i18n_core: Any) -> None:
    user = User.create_from_telegram(telegram_id=1)
    row = _stale(user, DownloadStatus.PENDING)

    with structlog.testing.capture_logs() as logs:
        await _use_case(FakeRequestRepository([row]), [user], FakeNotifier(), i18n_core).execute()

    entry = next(e for e in logs if e["event"] == "stale_request_reaped")
    assert entry["request_id"] == str(row.request_id)
    assert entry["user_id"] == str(user.id)
    assert entry["previous_status"] == DownloadStatus.PENDING
    assert entry["error_key"] == "error-request-stale"
    assert entry["log_level"] == "warning"


@pytest.mark.asyncio
async def test_unreachable_users_are_skipped_without_stopping_the_batch(i18n_core: Any) -> None:
    gone = _stale(User.create_from_telegram(telegram_id=1))  # user row deleted
    no_telegram = User(id=uuid4(), telegram_id=None)
    reachable = User.create_from_telegram(telegram_id=3)
    rows = [gone, _stale(no_telegram), _stale(reachable)]
    notifier = FakeNotifier()

    with structlog.testing.capture_logs() as logs:
        reaped = await _use_case(
            FakeRequestRepository(rows), [no_telegram, reachable], notifier, i18n_core
        ).execute()

    # Still reaped (the transition is already committed) — just nobody to tell.
    assert reaped == rows
    assert [chat for chat, _ in notifier.sent_texts] == [3]
    assert [e["request_id"] for e in logs if e["event"] == "stale_request_user_unreachable"] == [
        str(gone.request_id),
        str(rows[1].request_id),
    ]


@pytest.mark.asyncio
async def test_failed_notification_is_logged_and_the_rest_still_notified(i18n_core: Any) -> None:
    blocked = User.create_from_telegram(telegram_id=1)
    fine = User.create_from_telegram(telegram_id=2)
    rows = [_stale(blocked), _stale(fine)]
    notifier = FakeNotifier(failing_ids=frozenset({1}))

    with structlog.testing.capture_logs() as logs:
        reaped = await _use_case(
            FakeRequestRepository(rows), [blocked, fine], notifier, i18n_core
        ).execute()

    assert reaped == rows
    assert [chat for chat, _ in notifier.sent_texts] == [2]
    failure = next(e for e in logs if e["event"] == "stale_request_notify_failed")
    assert failure["request_id"] == str(rows[0].request_id)
    assert "blocked" in failure["error"]


@pytest.mark.asyncio
async def test_second_tick_does_not_notify_again(i18n_core: Any) -> None:
    user = User.create_from_telegram(telegram_id=1)
    repo = FakeRequestRepository([_stale(user)])
    notifier = FakeNotifier()
    use_case = _use_case(repo, [user], notifier, i18n_core)

    await use_case.execute()
    second = await use_case.execute()

    assert second == []
    assert len(notifier.sent_texts) == 1


@pytest.mark.asyncio
async def test_one_batch_per_tick(i18n_core: Any) -> None:
    user = User.create_from_telegram(telegram_id=1)
    repo = FakeRequestRepository([_stale(user) for _ in range(5)])
    use_case = _use_case(repo, [user], FakeNotifier(), i18n_core, batch_size=2)

    sizes = [len(await use_case.execute()) for _ in range(4)]

    assert sizes == [2, 2, 1, 0]
