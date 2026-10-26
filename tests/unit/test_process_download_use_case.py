"""ProcessDownloadUseCase tests using in-memory fakes — no DB, no yt-dlp,
no Telegram. Covers the three outcomes: success, download failure,
delivery failure.

Day 10: the use case now takes an ``error_localizer`` (worker-path
localization of categorized failures) and ``download_timeout_seconds``.
Failure-path assertions check that a localized message is sent, not raw
exception text (bug #6).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import structlog

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import ExtractionError, NotifierError
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.enums import DownloadStatus
from src.domain.value_objects.progress_phase import ProgressPhase
from tests.conftest import FakeErrorLocalizer

_CHAT_ID = 777
_MESSAGE_ID = 888


class FakeProgressPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def publish(self, request_id, chat_id, message_id, language, progress) -> None:
        self.calls.append((request_id, chat_id, message_id, language, progress))


_MAX_BYTES = 50 * 1024 * 1024
_TIMEOUT = 1800


class FakeDownloadRequestRepository:
    def __init__(self, request: DownloadRequest) -> None:
        self._request = request
        self.updates: list[DownloadStatus] = []

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return self._request if request_id == self._request.id else None

    async def create(self, download_request: DownloadRequest) -> DownloadRequest:
        raise NotImplementedError

    async def claim_for_processing(self, request_id: UUID) -> bool:
        self.updates.append(DownloadStatus.PROCESSING)
        return True

    async def update(self, download_request: DownloadRequest) -> None:
        self.updates.append(download_request.status)

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        raise NotImplementedError


class FakeUserRepository:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user if user_id == self._user.id else None

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        raise NotImplementedError

    async def create(self, user: User) -> User:
        raise NotImplementedError

    async def set_language(self, user_id: UUID, language: str) -> None:
        raise NotImplementedError


class FakeDownloader:
    def __init__(
        self,
        result_path: Path | None = None,
        error: Exception | None = None,
        result: DownloadResult | None = None,
    ) -> None:
        self._result_path = result_path
        self._error = error
        self._result = result

    async def get_preview(self, url: str):  # noqa: ANN201 — not exercised in these tests
        raise NotImplementedError

    async def download(
        self, url: str, options: DownloadOptions, progress_callback=None
    ) -> DownloadResult:
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        assert self._result_path is not None
        return DownloadResult(self._result_path)


class FakeStorage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path(f"/tmp/fake/{request_id}")

    async def release(self, request_id: UUID) -> None:
        return None

    async def available_bytes(self) -> int:
        return 10**12

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        return 0


class FakeNotifier:
    def __init__(self, fail_send_file: bool = False) -> None:
        self.fail_send_file = fail_send_file
        self.sent_files: list[tuple[int, Path]] = []
        self.sent_media: list[DeliverableMedia] = []
        self.sent_texts: list[tuple[int, str]] = []

    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        if self.fail_send_file:
            raise NotifierError("file too large")
        self.sent_files.append((telegram_id, media.path))
        self.sent_media.append(media)

    async def send_text(self, telegram_id: int, text: str) -> None:
        self.sent_texts.append((telegram_id, text))


def _make_request_and_user() -> tuple[DownloadRequest, User]:
    user = User.create_from_telegram(telegram_id=555)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")
    return request, user


def _use_case(
    request_repo,
    user_repo,
    downloader,
    notifier,
    localizer,
    progress_publisher=None,
    storage=None,
    min_free_disk_bytes=0,
) -> ProcessDownloadUseCase:
    return ProcessDownloadUseCase(
        download_request_repository=request_repo,
        user_repository=user_repo,
        downloader=downloader,
        storage=storage or FakeStorage(),
        notifier=notifier,
        error_localizer=localizer,
        progress_publisher=progress_publisher or FakeProgressPublisher(),
        max_deliverable_file_size_bytes=_MAX_BYTES,
        download_timeout_seconds=_TIMEOUT,
        min_free_disk_bytes=min_free_disk_bytes,
    )


@pytest.mark.asyncio
async def test_successful_download_marks_done_and_sends_file(i18n_core) -> None:
    request, user = _make_request_and_user()
    result_path = Path("/tmp/fake/video.mp4")

    request_repo = FakeDownloadRequestRepository(request)
    notifier = FakeNotifier()
    use_case = _use_case(
        request_repo,
        FakeUserRepository(user),
        FakeDownloader(result_path=result_path),
        notifier,
        FakeErrorLocalizer(i18n_core),
    )
    await use_case.execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert request.status == DownloadStatus.DONE
    assert request_repo.updates == [DownloadStatus.PROCESSING, DownloadStatus.DONE]
    assert notifier.sent_files == [(555, result_path)]


@pytest.mark.asyncio
async def test_download_failure_marks_failed_and_notifies_text(i18n_core) -> None:
    request, user = _make_request_and_user()

    request_repo = FakeDownloadRequestRepository(request)
    notifier = FakeNotifier()
    localizer = FakeErrorLocalizer(i18n_core)
    use_case = _use_case(
        request_repo,
        FakeUserRepository(user),
        FakeDownloader(error=ExtractionError()),
        notifier,
        localizer,
    )
    await use_case.execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert request.status == DownloadStatus.FAILED
    assert request_repo.updates == [DownloadStatus.PROCESSING, DownloadStatus.FAILED]
    assert notifier.sent_files == []
    assert len(notifier.sent_texts) == 1
    assert notifier.sent_texts[0][0] == 555
    # A localized, categorized message — not raw exception text.
    assert notifier.sent_texts[0][1] == localizer.localize("error-extraction-failed", user.language)


@pytest.mark.asyncio
async def test_delivery_failure_marks_failed_and_notifies_text(i18n_core) -> None:
    request, user = _make_request_and_user()
    result_path = Path("/tmp/fake/video.mp4")

    request_repo = FakeDownloadRequestRepository(request)
    notifier = FakeNotifier(fail_send_file=True)
    use_case = _use_case(
        request_repo,
        FakeUserRepository(user),
        FakeDownloader(result_path=result_path),
        notifier,
        FakeErrorLocalizer(i18n_core),
    )
    await use_case.execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert request.status == DownloadStatus.FAILED
    assert len(notifier.sent_texts) == 1


@pytest.mark.asyncio
async def test_unknown_request_id_is_a_noop(i18n_core) -> None:
    request, user = _make_request_and_user()
    request_repo = FakeDownloadRequestRepository(request)
    notifier = FakeNotifier()
    use_case = _use_case(
        request_repo,
        FakeUserRepository(user),
        FakeDownloader(),
        notifier,
        FakeErrorLocalizer(i18n_core),
    )

    from uuid import uuid4

    await use_case.execute(uuid4(), _CHAT_ID, _MESSAGE_ID)

    assert request_repo.updates == []
    assert notifier.sent_files == []
    assert notifier.sent_texts == []


class _InactiveRequestRepository(FakeDownloadRequestRepository):
    """The claim fails: the reaper already failed the request, or a
    duplicate job finds it finished."""

    async def claim_for_processing(self, request_id: UUID) -> bool:
        return False


class _NeverCalledDownloader(FakeDownloader):
    async def download(self, url, options, progress_callback=None) -> DownloadResult:
        raise AssertionError("an inactive request must not be downloaded")


@pytest.mark.asyncio
async def test_request_that_cannot_be_claimed_is_skipped_silently(i18n_core) -> None:
    request, user = _make_request_and_user()
    request_repo = _InactiveRequestRepository(request)
    notifier = FakeNotifier()
    publisher = FakeProgressPublisher()

    await _use_case(
        request_repo,
        FakeUserRepository(user),
        _NeverCalledDownloader(),
        notifier,
        FakeErrorLocalizer(i18n_core),
        publisher,
    ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    # The user was already told (by the reaper); nothing else happens.
    assert request_repo.updates == []
    assert notifier.sent_texts == []
    assert notifier.sent_files == []
    assert publisher.calls == []
    assert request.status == DownloadStatus.PENDING


# --- disk guard (ADR 0005) ---------------------------------------------------


class _RecordingStorage(FakeStorage):
    def __init__(self, available: int = 10**12) -> None:
        self.available = available
        self.released: list[UUID] = []
        self.availability_checks = 0

    async def release(self, request_id: UUID) -> None:
        self.released.append(request_id)

    async def available_bytes(self) -> int:
        self.availability_checks += 1
        return self.available


class _ExplodingDownloader(FakeDownloader):
    async def download(self, url, options, progress_callback=None) -> DownloadResult:
        raise RuntimeError("yt-dlp internals blew up")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("downloader", "fail_send_file"),
    [
        (FakeDownloader(result_path=Path("/tmp/fake/v.mp4")), False),  # delivered
        (FakeDownloader(error=ExtractionError()), False),  # download failed
        (FakeDownloader(result_path=Path("/tmp/fake/v.mp4")), True),  # delivery failed
    ],
    ids=["done", "download-failed", "delivery-failed"],
)
async def test_request_directory_is_released_however_the_job_ends(
    i18n_core, downloader, fail_send_file
) -> None:
    request, user = _make_request_and_user()
    storage = _RecordingStorage()

    await _use_case(
        FakeDownloadRequestRepository(request),
        FakeUserRepository(user),
        downloader,
        FakeNotifier(fail_send_file=fail_send_file),
        FakeErrorLocalizer(i18n_core),
        storage=storage,
    ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert storage.released == [request.id]


@pytest.mark.asyncio
async def test_directory_is_released_even_when_the_download_raises_unexpectedly(
    i18n_core,
) -> None:
    request, user = _make_request_and_user()
    storage = _RecordingStorage()

    with pytest.raises(RuntimeError):
        await _use_case(
            FakeDownloadRequestRepository(request),
            FakeUserRepository(user),
            _ExplodingDownloader(),
            FakeNotifier(),
            FakeErrorLocalizer(i18n_core),
            storage=storage,
        ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert storage.released == [request.id]


@pytest.mark.asyncio
async def test_unclaimed_request_does_not_touch_storage(i18n_core) -> None:
    """The directory may belong to whoever does own the request."""
    request, user = _make_request_and_user()
    storage = _RecordingStorage()

    await _use_case(
        _InactiveRequestRepository(request),
        FakeUserRepository(user),
        _NeverCalledDownloader(),
        FakeNotifier(),
        FakeErrorLocalizer(i18n_core),
        storage=storage,
        min_free_disk_bytes=1,
    ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert storage.released == []
    assert storage.availability_checks == 0


@pytest.mark.asyncio
async def test_low_disk_refuses_the_download_and_tells_the_user(i18n_core) -> None:
    request, user = _make_request_and_user()
    request_repo = FakeDownloadRequestRepository(request)
    storage = _RecordingStorage(available=999)
    notifier = FakeNotifier()
    publisher = FakeProgressPublisher()
    localizer = FakeErrorLocalizer(i18n_core)

    with structlog.testing.capture_logs() as logs:
        await _use_case(
            request_repo,
            FakeUserRepository(user),
            _NeverCalledDownloader(),
            notifier,
            localizer,
            publisher,
            storage=storage,
            min_free_disk_bytes=1000,
        ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert request_repo.updates == [DownloadStatus.PROCESSING, DownloadStatus.FAILED]
    assert notifier.sent_texts == [(555, localizer.localize("error-storage-full", user.language))]
    assert publisher.calls[-1][4].phase == ProgressPhase.FAILED
    assert storage.released == [request.id]
    entry = next(e for e in logs if e["event"] == "process_download_rejected_low_disk")
    assert entry["request_id"] == str(request.id)
    assert entry["available_bytes"] == 999
    assert entry["min_free_bytes"] == 1000
    assert entry["error_key"] == "error-storage-full"


@pytest.mark.asyncio
async def test_free_space_exactly_at_the_floor_is_enough(i18n_core) -> None:
    request, user = _make_request_and_user()
    request_repo = FakeDownloadRequestRepository(request)

    await _use_case(
        request_repo,
        FakeUserRepository(user),
        FakeDownloader(result_path=Path("/tmp/fake/v.mp4")),
        FakeNotifier(),
        FakeErrorLocalizer(i18n_core),
        storage=_RecordingStorage(available=1000),
        min_free_disk_bytes=1000,
    ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert request_repo.updates == [DownloadStatus.PROCESSING, DownloadStatus.DONE]


@pytest.mark.asyncio
async def test_zero_floor_disables_the_check(i18n_core) -> None:
    request, user = _make_request_and_user()
    storage = _RecordingStorage(available=0)

    await _use_case(
        FakeDownloadRequestRepository(request),
        FakeUserRepository(user),
        FakeDownloader(result_path=Path("/tmp/fake/v.mp4")),
        FakeNotifier(),
        FakeErrorLocalizer(i18n_core),
        storage=storage,
        min_free_disk_bytes=0,
    ).execute(request.id, _CHAT_ID, _MESSAGE_ID)

    assert storage.availability_checks == 0
    assert request.status == DownloadStatus.DONE
