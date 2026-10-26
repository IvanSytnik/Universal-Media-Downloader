"""RequestDownloadUseCase tests using in-memory fakes — no DB, no queue."""

from __future__ import annotations

from uuid import UUID

import pytest

from src.application.policies.format_policy import FormatPolicy
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import FormatNotAllowedError, UnsupportedURLError
from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)
from src.domain.value_objects.format_kind import FormatKind


class FakeUserRepository:
    def __init__(self, existing_user: User | None = None) -> None:
        self._users: dict[UUID, User] = {}
        if existing_user is not None:
            self._users[existing_user.id] = existing_user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        for user in self._users.values():
            if user.telegram_id == telegram_id:
                return user
        return None

    async def create(self, user: User) -> User:
        self._users[user.id] = user
        return user


class FakeDownloadRequestRepository:
    def __init__(self) -> None:
        self.created: list[DownloadRequest] = []

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return next((r for r in self.created if r.id == request_id), None)

    async def create(self, download_request: DownloadRequest) -> DownloadRequest:
        self.created.append(download_request)
        return download_request

    async def update(self, download_request: DownloadRequest) -> None:
        pass

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        return [r for r in self.created if r.user_id == user_id]


class FakeTaskQueue:
    def __init__(self) -> None:
        self.enqueued_download_ids: list[UUID] = []
        self.enqueued_coordinates: list[tuple[int, int]] = []

    async def enqueue_ping(self, message: str) -> str:
        return "fake-ping-job"

    async def enqueue_download(self, request_id: UUID, chat_id: int, message_id: int) -> str:
        self.enqueued_download_ids.append(request_id)
        self.enqueued_coordinates.append((chat_id, message_id))
        return "fake-download-job"


@pytest.mark.asyncio
async def test_creates_request_for_existing_user() -> None:
    existing_user = User.create_from_telegram(telegram_id=42)
    user_repo = FakeUserRepository(existing_user=existing_user)
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()

    use_case = RequestDownloadUseCase(user_repo, request_repo, task_queue, FormatPolicy({}))
    request = await use_case.execute(
        telegram_id=42,
        url="https://example.com/video",
        spec=DEFAULT_DOWNLOAD_SPEC,
        extractor_key="youtube",
        chat_id=1,
        message_id=2,
    )

    assert request.user_id == existing_user.id
    assert request.source_url == "https://example.com/video"
    assert request in request_repo.created
    assert task_queue.enqueued_download_ids == [request.id]


@pytest.mark.asyncio
async def test_registers_new_user_on_the_fly() -> None:
    user_repo = FakeUserRepository()
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()

    use_case = RequestDownloadUseCase(user_repo, request_repo, task_queue, FormatPolicy({}))
    request = await use_case.execute(
        telegram_id=999,
        url="https://example.com/video",
        spec=DEFAULT_DOWNLOAD_SPEC,
        extractor_key="youtube",
        chat_id=1,
        message_id=2,
    )

    created_user = await user_repo.get_by_telegram_id(999)
    assert created_user is not None
    assert request.user_id == created_user.id


@pytest.mark.asyncio
async def test_rejects_malformed_url_before_touching_repo_or_queue() -> None:
    user_repo = FakeUserRepository(existing_user=User.create_from_telegram(telegram_id=1))
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()

    use_case = RequestDownloadUseCase(user_repo, request_repo, task_queue, FormatPolicy({}))

    with pytest.raises(UnsupportedURLError):
        await use_case.execute(
            telegram_id=1,
            url="not-a-url",
            spec=DEFAULT_DOWNLOAD_SPEC,
            extractor_key="youtube",
            chat_id=1,
            message_id=2,
        )

    assert request_repo.created == []
    assert task_queue.enqueued_download_ids == []


# --- Day 11C (v2): FormatPolicy enforcement -----------------------------------

_NO_YOUTUBE_AUDIO = FormatPolicy({"youtube": [FormatKind.AUDIO]})


@pytest.mark.parametrize("extractor_key", ["youtube", "YouTube"])
@pytest.mark.asyncio
async def test_disallowed_spec_is_refused_before_anything_is_persisted(
    extractor_key: str,
) -> None:
    # A stale card (rendered before the switch was flipped) or a forged
    # callback lands here; nothing may be created or enqueued.
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()
    use_case = RequestDownloadUseCase(
        FakeUserRepository(User.create_from_telegram(42)),
        request_repo,
        task_queue,
        _NO_YOUTUBE_AUDIO,
    )

    with pytest.raises(FormatNotAllowedError):
        await use_case.execute(
            42,
            "https://youtube.com/watch?v=x",
            AudioSpec(),
            extractor_key,
            chat_id=1,
            message_id=2,
        )

    assert request_repo.created == []
    assert task_queue.enqueued_download_ids == []


@pytest.mark.parametrize(
    ("spec", "extractor_key"),
    [
        (VideoSpec(VideoTier.P1080), "youtube"),  # other kind, same source
        (AudioSpec(), "tiktok"),  # same kind, other source
    ],
)
@pytest.mark.asyncio
async def test_kill_switch_is_scoped_to_kind_and_extractor(
    spec: DownloadSpec, extractor_key: str
) -> None:
    request_repo = FakeDownloadRequestRepository()
    use_case = RequestDownloadUseCase(
        FakeUserRepository(User.create_from_telegram(42)),
        request_repo,
        FakeTaskQueue(),
        _NO_YOUTUBE_AUDIO,
    )

    request = await use_case.execute(
        42, "https://example.com/v", spec, extractor_key, chat_id=1, message_id=2
    )

    assert request.spec == spec
    assert len(request_repo.created) == 1
