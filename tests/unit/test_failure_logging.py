"""Day 11C stage 5: the diagnostic log lines on failure paths are pinned.

Why this module exists: the project's contract with the user is bug #6 —
the user gets a short, keyed, localized message and NOTHING else, while
the raw diagnosis (yt-dlp's text, the offending column, the request id)
goes to the log. The message half was tested from Day 10. The log half
was tested nowhere: an audit before this (`grep -rn caplog tests/`) found
zero assertions on logging anywhere in the suite. So half of that
contract could be deleted line by line without a single test failing,
and the first sign would be an unfixable production incident with no
request_id to grep for.

These tests cover the failure paths specifically, not every log call.
An `info` line that says a happy path happened is cheap to lose; the
lines that exist *because* something broke are the ones worth guarding.

Captured with structlog.testing.capture_logs, never caplog — structlog
isn't wired to stdlib logging here, so caplog.text is always empty and
assertions against it pass vacuously (lesson 11C.4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import (
    CorruptedRecordError,
    DownloadTimeoutError,
    ExtractionError,
    FileTooLargeError,
    PrivateContentError,
)
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_result import DownloadResult
from src.infrastructure.downloader import ytdlp_downloader
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader

_SECRET = "https://cdn.example.com/signed?token=SUPERSECRET&exp=1"


# --- worker failure path -----------------------------------------------------


class _Repo:
    def __init__(self, request: DownloadRequest | None, exc: Exception | None = None) -> None:
        self._request = request
        self._exc = exc
        self.failed_by_id: list[UUID] = []

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        if self._exc is not None:
            raise self._exc
        return self._request

    async def claim_for_processing(self, request_id: UUID) -> bool:
        return True

    async def update(self, request: DownloadRequest) -> None:
        return None

    async def mark_failed_by_id(self, request_id: UUID) -> None:
        self.failed_by_id.append(request_id)


class _UserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user


class _FailingDownloader:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def download(
        self, url: str, options: Any, progress_callback: Any = None
    ) -> DownloadResult:
        raise self._exc

    async def get_preview(self, url: str) -> Any:  # pragma: no cover
        raise NotImplementedError


class _Storage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path("/tmp/umd-test")

    async def release(self, request_id: UUID) -> None:
        return None

    async def available_bytes(self) -> int:
        return 10**12

    async def cleanup_expired(self, max_age_seconds: int) -> int:  # pragma: no cover
        return 0


class _Notifier:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: Any = None
    ) -> None:
        raise AssertionError("not reached")  # pragma: no cover

    async def send_text(self, telegram_id: int, text: str) -> None:
        self.texts.append(text)


class _Localizer:
    def localize(self, error_key: str, locale: str | None = None, **kwargs: Any) -> str:
        return f"<{error_key}>"


class _Pub:
    async def publish(self, *args: Any, **kwargs: Any) -> None:
        return None


def _use_case(repo: _Repo, notifier: _Notifier, downloader: Any) -> ProcessDownloadUseCase:
    return ProcessDownloadUseCase(
        download_request_repository=repo,  # type: ignore[arg-type]
        user_repository=_UserRepo(User(id=uuid4(), telegram_id=7)),  # type: ignore[arg-type]
        downloader=downloader,
        storage=_Storage(),  # type: ignore[arg-type]
        notifier=notifier,  # type: ignore[arg-type]
        error_localizer=_Localizer(),  # type: ignore[arg-type]
        progress_publisher=_Pub(),  # type: ignore[arg-type]
        max_deliverable_file_size_bytes=1,
        download_timeout_seconds=1,
        min_free_disk_bytes=0,
    )


@pytest.mark.asyncio
async def test_download_failure_logs_request_id_and_error_key() -> None:
    """Without request_id the line can't be tied to a user's complaint;
    without error_key you can't tell which category was reported."""
    request = DownloadRequest.create(user_id=uuid4(), source_url="https://example.com/x")
    repo = _Repo(request)
    notifier = _Notifier()

    with structlog.testing.capture_logs() as logs:
        await _use_case(repo, notifier, _FailingDownloader(PrivateContentError())).execute(
            request.id, chat_id=1, message_id=2
        )

    failures = [entry for entry in logs if entry["event"] == "process_download_failed"]
    assert len(failures) == 1
    entry = failures[0]
    assert entry["log_level"] == "warning"
    assert entry["request_id"] == str(request.id)
    assert entry["error_key"] == "error-private"


@pytest.mark.asyncio
async def test_diagnostics_go_to_the_log_and_not_to_the_user() -> None:
    """Bug #6, both halves in one test: the raw text must appear in the
    log AND must not appear in what the user is sent. Asserting only the
    second half would be satisfied by not logging at all."""
    request = DownloadRequest.create(user_id=uuid4(), source_url="https://example.com/x")
    repo = _Repo(request)
    notifier = _Notifier()

    with structlog.testing.capture_logs() as logs:
        await _use_case(repo, notifier, _FailingDownloader(PrivateContentError(_SECRET))).execute(
            request.id, chat_id=1, message_id=2
        )

    logged = [entry for entry in logs if entry["event"] == "process_download_failed"][0]
    assert _SECRET in logged["error"]
    assert notifier.texts == ["<error-private>"]
    assert _SECRET not in notifier.texts[0]


@pytest.mark.asyncio
async def test_corrupted_record_logs_the_column_and_the_raw_value() -> None:
    # The whole point of this line: find the bad row afterwards.
    request_id, user_id = uuid4(), uuid4()
    repo = _Repo(
        None,
        CorruptedRecordError(
            column="status", raw_value="garbage", request_id=request_id, user_id=user_id
        ),
    )
    notifier = _Notifier()

    with structlog.testing.capture_logs() as logs:
        await _use_case(repo, notifier, _FailingDownloader(RuntimeError())).execute(
            request_id, chat_id=1, message_id=2
        )

    entry = [e for e in logs if e["event"] == "process_download_corrupted_record"][0]
    assert entry["log_level"] == "error"
    assert entry["request_id"] == str(request_id)
    assert entry["user_id"] == str(user_id)
    assert entry["column"] == "status"
    assert entry["raw_value"] == "garbage"


@pytest.mark.asyncio
async def test_missing_request_is_logged_not_silently_dropped() -> None:
    # A job for a request that vanished returns early; without this line
    # it would return early and leave no trace at all.
    repo = _Repo(None)
    missing = uuid4()

    with structlog.testing.capture_logs() as logs:
        await _use_case(repo, _Notifier(), _FailingDownloader(RuntimeError())).execute(
            missing, chat_id=1, message_id=2
        )

    entry = [e for e in logs if e["event"] == "process_download_request_not_found"][0]
    assert entry["request_id"] == str(missing)


# --- downloader failure paths ------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raised", "expected_reason", "expected_domain_error"),
    [
        (ytdlp_downloader._DownloadTimeoutError(_SECRET), "timeout", DownloadTimeoutError),
        (ytdlp_downloader._DownloadProcessError(_SECRET), "process_error", ExtractionError),
        (ytdlp_downloader._DownloadExtractError(_SECRET), "extract_error", ExtractionError),
    ],
)
async def test_download_failure_logs_a_reason_and_the_raw_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raised: Exception,
    expected_reason: str,
    expected_domain_error: type[Exception],
) -> None:
    """``reason`` is what makes these four call sites distinguishable in
    an aggregated log — a timeout and a crashed child both surface to the
    user as one generic message, so the log is the only place they differ.

    The expected domain type is asserted per case rather than a blind
    ``Exception``: the adapter's job is to translate library failures
    into the domain's vocabulary, and "it raised something" would pass
    even if that translation broke.
    """

    def _raise(*args: Any, **kwargs: Any) -> str:
        raise raised

    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", _raise)

    with structlog.testing.capture_logs() as logs, pytest.raises(expected_domain_error):
        await YtDlpDownloader(preview_timeout_seconds=60).download(
            "https://example.com/v", DownloadOptions(output_dir=tmp_path)
        )

    entry = [e for e in logs if e["event"] == "download_failed"][0]
    assert entry["reason"] == expected_reason
    assert entry["url"] == "https://example.com/v"
    # Signed CDN URLs and container paths live here, never in a message.
    assert _SECRET in entry["error"]


@pytest.mark.asyncio
async def test_file_too_large_logs_reason_and_still_carries_numbers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> str:
        raise ytdlp_downloader._FileTooLargeError(estimated_mb=2100, limit_mb=2000)

    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", _raise)

    with structlog.testing.capture_logs() as logs, pytest.raises(FileTooLargeError) as caught:
        await YtDlpDownloader(preview_timeout_seconds=60).download(
            "https://example.com/v", DownloadOptions(output_dir=tmp_path)
        )

    assert [e for e in logs if e["event"] == "download_failed"][0]["reason"] == "too_large"
    # The size IS actionable information, so unlike the other categories
    # it legitimately reaches the user — as Fluent arguments, not text.
    assert caught.value.estimated_mb == 2100
    assert caught.value.limit_mb == 2000


@pytest.mark.asyncio
async def test_success_is_logged_with_the_resulting_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The one happy-path line worth pinning: it's what tells you WHICH
    # file a delivery failure was about.
    produced = str(tmp_path / "v.mp4")
    monkeypatch.setattr(
        ytdlp_downloader,
        "_run_download_in_process",
        lambda *a, **kw: DownloadResult(Path(produced)),
    )

    with structlog.testing.capture_logs() as logs:
        await YtDlpDownloader(preview_timeout_seconds=60).download(
            "https://example.com/v", DownloadOptions(output_dir=tmp_path)
        )

    entry = [e for e in logs if e["event"] == "download_succeeded"][0]
    assert entry["path"] == produced
    assert entry["url"] == "https://example.com/v"


# --- notifier + progress listener failure paths ------------------------------


class _BrokenBot:
    """Bot stand-in whose every call fails the way Telegram does."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def send_document(self, **kwargs: Any) -> None:
        raise self._exc

    async def send_message(self, **kwargs: Any) -> None:
        raise self._exc

    async def edit_message_text(self, **kwargs: Any) -> None:
        raise self._exc


@pytest.mark.asyncio
async def test_notifier_send_text_failure_logs_the_recipient() -> None:
    """Delivery failures are per-user (blocked bot, deleted chat), so the
    telegram_id is the field that makes the line actionable."""
    from aiogram.exceptions import TelegramAPIError

    from src.domain.exceptions import NotifierError
    from src.infrastructure.notifier.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier(
        _BrokenBot(TelegramAPIError(method=None, message="bot was blocked")),  # type: ignore[arg-type]
        max_file_size_bytes=1,
        file_upload_timeout_seconds=1,
    )

    with structlog.testing.capture_logs() as logs, pytest.raises(NotifierError):
        await notifier.send_text(4242, "hi")

    entry = [e for e in logs if e["event"] == "notifier_send_text_failed"][0]
    assert entry["telegram_id"] == 4242
    assert "blocked" in entry["error"]


@pytest.mark.asyncio
async def test_progress_listener_logs_a_bad_payload(i18n_core: Any) -> None:
    """The publisher and the listener are separate processes: a payload
    the listener can't parse means a version skew, and the channel name
    carries the request id needed to trace it."""
    from src.presentation.telegram.i18n import DEFAULT_LOCALE
    from src.presentation.telegram.progress_listener import TelegramProgressListener

    listener = TelegramProgressListener(
        bot=_BrokenBot(RuntimeError()),  # type: ignore[arg-type]
        redis=object(),  # type: ignore[arg-type]
        i18n_core=i18n_core,
        default_locale=DEFAULT_LOCALE,
    )

    with structlog.testing.capture_logs() as logs:
        await listener._handle_message(
            {"type": "pmessage", "channel": "umd:progress:req-9", "data": b"not json"}
        )

    entry = [e for e in logs if e["event"] == "progress_listener_bad_payload"][0]
    assert entry["channel"] == "umd:progress:req-9"


@pytest.mark.asyncio
async def test_progress_listener_logs_missing_coordinates(i18n_core: Any) -> None:
    from src.presentation.telegram.i18n import DEFAULT_LOCALE
    from src.presentation.telegram.progress_listener import TelegramProgressListener

    listener = TelegramProgressListener(
        bot=_BrokenBot(RuntimeError()),  # type: ignore[arg-type]
        redis=object(),  # type: ignore[arg-type]
        i18n_core=i18n_core,
        default_locale=DEFAULT_LOCALE,
    )

    with structlog.testing.capture_logs() as logs:
        # A payload with no chat_id/message_id — nowhere to render, so the
        # listener drops it. Silently dropping would be indistinguishable
        # from "progress just never appeared".
        await listener._handle_message(
            {
                "type": "pmessage",
                "channel": "umd:progress:req-9",
                "data": b'{"percent": 10}',
            }
        )

    entry = [e for e in logs if e["event"] == "progress_listener_missing_coordinates"][0]
    assert entry["channel"] == "umd:progress:req-9"
