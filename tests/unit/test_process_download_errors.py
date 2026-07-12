"""Tests for ProcessDownloadUseCase failure localization (Day 10).

Covers the worker path: a categorized downloader error must reach the
user as a localized message in THEIR language (User.language), never as
raw exception text (bug #6), and must not depend on an aiogram
I18nContext (there is none in the worker).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from aiogram_i18n.cores import FluentRuntimeCore

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.exceptions import (
    ExtractionError,
    FileTooLargeError,
    PrivateContentError,
    UnsupportedURLError,
)
from src.infrastructure.localization.fluent_error_localizer import FluentErrorLocalizer
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core


class _Request:
    def __init__(self, user_id: UUID) -> None:
        self.id = uuid4()
        self.user_id = user_id
        self.source_url = "https://example.com/x"
        self.status = "pending"

    def mark_processing(self) -> None:
        self.status = "processing"

    def mark_failed(self) -> None:
        self.status = "failed"

    def mark_done(self) -> None:
        self.status = "done"


class _User:
    def __init__(self, language: str | None) -> None:
        self.id = uuid4()
        self.telegram_id = 123
        self.language = language


class _RequestRepo:
    def __init__(self, request: _Request) -> None:
        self._request = request
        self.updated: list[str] = []

    async def get_by_id(self, request_id: UUID) -> _Request:
        return self._request

    async def update(self, request: _Request) -> None:
        self.updated.append(request.status)


class _UserRepo:
    def __init__(self, user: _User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> _User:
        return self._user

    async def set_language(self, user_id: UUID, language: str) -> None: ...


class _FailingDownloader:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def download(self, url: str, options: object) -> Path:
        raise self._exc

    async def get_preview(self, url: str) -> object:  # pragma: no cover
        raise NotImplementedError


class _Storage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path("/tmp/umd-test")

    async def cleanup_expired(self, max_age_seconds: int) -> int:  # pragma: no cover
        return 0


class _CapturingNotifier:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_file(
        self, telegram_id: int, file_path: Path, caption: str | None = None
    ) -> None:
        raise AssertionError("should not be called on a download failure")
    
    async def send_text(self, telegram_id: int, text: str) -> None:
        self.texts.append(text)


@pytest.fixture
async def localizer() -> FluentErrorLocalizer:
    core: FluentRuntimeCore = create_i18n_core()
    await core.startup()
    return FluentErrorLocalizer(core, default_locale=DEFAULT_LOCALE)


async def _run(exc: Exception, language: str | None, localizer: FluentErrorLocalizer) -> str:
    user = _User(language)
    request = _Request(user.id)
    notifier = _CapturingNotifier()
    use_case = ProcessDownloadUseCase(
        download_request_repository=_RequestRepo(request),
        user_repository=_UserRepo(user),
        downloader=_FailingDownloader(exc),
        storage=_Storage(),
        notifier=notifier,
        error_localizer=localizer,
        max_deliverable_file_size_bytes=2000 * 1024 * 1024,
        download_timeout_seconds=1800,
    )
    await use_case.execute(request.id)
    assert request.status == "failed"
    assert len(notifier.texts) == 1
    return notifier.texts[0]


async def test_private_localized_ru(localizer: FluentErrorLocalizer) -> None:
    msg = await _run(PrivateContentError(), "ru", localizer)
    assert msg == localizer.localize("error-private", "ru")


async def test_private_localized_en(localizer: FluentErrorLocalizer) -> None:
    msg = await _run(PrivateContentError(), "en", localizer)
    assert msg == localizer.localize("error-private", "en")


async def test_none_language_uses_default(localizer: FluentErrorLocalizer) -> None:
    msg = await _run(PrivateContentError(), None, localizer)
    assert msg == localizer.localize("error-private", None)


async def test_too_large_carries_numbers(localizer: FluentErrorLocalizer) -> None:
    msg = await _run(FileTooLargeError(estimated_mb=2100, limit_mb=2000), "en", localizer)
    assert msg == localizer.localize("error-too-large", "en", estimated_mb=2100, limit_mb=2000)


async def test_generic_extraction_error(localizer: FluentErrorLocalizer) -> None:
    msg = await _run(ExtractionError(), "ru", localizer)
    assert msg == localizer.localize("error-extraction-failed", "ru")


async def test_unsupported_url(localizer: FluentErrorLocalizer) -> None:
    msg = await _run(UnsupportedURLError(), "en", localizer)
    assert msg == localizer.localize("error-unsupported-site", "en")


async def test_no_raw_exception_text_leaks(localizer: FluentErrorLocalizer) -> None:
    # A categorized error must never surface str(exc) / diagnostics.
    class _Leaky(PrivateContentError):
        def __str__(self) -> str:
            return "INTERNAL DIAGNOSTIC /tmp/secret signed_cdn_url=..."

    msg = await _run(_Leaky(), "en", localizer)
    assert "INTERNAL" not in msg
    assert "secret" not in msg
