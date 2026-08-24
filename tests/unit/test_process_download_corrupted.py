"""Day 11C.3: the worker reports an unreadable row instead of dying on it.

This is the read-side half of the hardening — test_corrupted_record.py
covers the parsing policy, this covers what the worker DOES with it.

The failure arrives from ``get_by_id``, before the entity exists, so
none of the normal failure machinery applies: there is no request to
``mark_failed()`` and no user loaded to notify. The recovery has to work
off the two uuid columns the exception carries out of the failed read.

What must hold (bugs #6/#13): the request ends up FAILED, the user gets
exactly one short message in THEIR language resolved from the real FTL
files, and no raw diagnostics (column name, garbage value) appear in it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from aiogram_i18n.cores import FluentRuntimeCore

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.exceptions import CorruptedRecordError
from src.infrastructure.localization.fluent_error_localizer import FluentErrorLocalizer
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core


class _User:
    def __init__(self, language: str | None) -> None:
        self.id = uuid4()
        self.telegram_id = 123
        self.language = language


class _CorruptedRequestRepo:
    """get_by_id raises the way the real repository does for a row whose
    stored status can't be parsed."""

    def __init__(self, request_id: UUID, user_id: UUID) -> None:
        self._request_id = request_id
        self._user_id = user_id
        self.failed_by_id: list[UUID] = []
        self.updated: list[object] = []

    async def get_by_id(self, request_id: UUID) -> object:
        raise CorruptedRecordError(
            column="status",
            raw_value="garbage",
            request_id=self._request_id,
            user_id=self._user_id,
        )

    async def update(self, request: object) -> None:  # pragma: no cover - must not run
        self.updated.append(request)

    async def mark_failed_by_id(self, request_id: UUID) -> None:
        self.failed_by_id.append(request_id)


class _UserRepo:
    def __init__(self, user: _User | None) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> _User | None:
        return self._user


class _CapturingNotifier:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_file(
        self, telegram_id: int, file_path: Path, caption: str | None = None
    ) -> None:  # pragma: no cover - never reached
        raise AssertionError("should not deliver anything for a corrupted row")

    async def send_text(self, telegram_id: int, text: str) -> None:
        self.texts.append(text)


class _ExplodingDownloader:
    async def download(
        self, url: str, options: object, progress_callback: object = None
    ) -> Path:  # pragma: no cover - must never be reached
        raise AssertionError("must not start a download for an unreadable row")

    async def get_preview(self, url: str) -> object:  # pragma: no cover
        raise NotImplementedError


class _Storage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path("/tmp/umd-test")

    async def cleanup_expired(self, max_age_seconds: int) -> int:  # pragma: no cover
        return 0


class _NoopProgressPublisher:
    async def publish(
        self, request_id: object, chat_id: int, message_id: int, language: object, progress: object
    ) -> None:  # pragma: no cover
        pass


@pytest.fixture
async def localizer() -> FluentErrorLocalizer:
    core: FluentRuntimeCore = create_i18n_core()
    await core.startup()
    return FluentErrorLocalizer(core, default_locale=DEFAULT_LOCALE)


async def _run(
    language: str | None, localizer: FluentErrorLocalizer, *, user_found: bool = True
) -> tuple[_CorruptedRequestRepo, _CapturingNotifier, UUID]:
    user = _User(language)
    request_id = uuid4()
    repo = _CorruptedRequestRepo(request_id, user.id)
    notifier = _CapturingNotifier()

    use_case = ProcessDownloadUseCase(
        download_request_repository=repo,
        user_repository=_UserRepo(user if user_found else None),
        downloader=_ExplodingDownloader(),
        storage=_Storage(),
        notifier=notifier,
        error_localizer=localizer,
        progress_publisher=_NoopProgressPublisher(),
        max_deliverable_file_size_bytes=2000 * 1024 * 1024,
        download_timeout_seconds=1800,
    )
    await use_case.execute(request_id, chat_id=777, message_id=888)
    return repo, notifier, request_id


async def test_user_gets_one_localized_message_ru(localizer: FluentErrorLocalizer) -> None:
    _, notifier, _ = await _run("ru", localizer)
    assert notifier.texts == [localizer.localize("error-internal", "ru")]


async def test_user_gets_one_localized_message_en(localizer: FluentErrorLocalizer) -> None:
    _, notifier, _ = await _run("en", localizer)
    assert notifier.texts == [localizer.localize("error-internal", "en")]


async def test_none_language_falls_back_to_default(localizer: FluentErrorLocalizer) -> None:
    _, notifier, _ = await _run(None, localizer)
    assert notifier.texts == [localizer.localize("error-internal", None)]


async def test_message_leaks_no_diagnostics(localizer: FluentErrorLocalizer) -> None:
    # Bug #6: the column name and the garbage value belong in the log,
    # never in what the user reads.
    _, notifier, _ = await _run("ru", localizer)
    assert "garbage" not in notifier.texts[0]
    assert "status" not in notifier.texts[0]


async def test_request_is_marked_failed_by_id(localizer: FluentErrorLocalizer) -> None:
    repo, _, request_id = await _run("ru", localizer)
    # By id, because the entity is precisely what couldn't be built.
    assert repo.failed_by_id == [request_id]
    assert repo.updated == []


async def test_unreachable_user_still_fails_the_request(localizer: FluentErrorLocalizer) -> None:
    # No user row to notify — the request must still not stay stuck in
    # its old status, and nothing may be sent.
    repo, notifier, request_id = await _run("ru", localizer, user_found=False)
    assert repo.failed_by_id == [request_id]
    assert notifier.texts == []
