"""ProcessDownloadUseCase — progress wiring (Day 11B).

Regression-guard style, mirroring 11A.1's lesson: a fake
ProgressPublisherPort CAPTURES exactly what it was called with (not a
bare mock asserting "was called"), so a wiring bug — wrong request_id,
stale language, wrong chat/message coordinates — actually fails the test.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.download_result import DownloadResult

_MAX_BYTES = 50 * 1024 * 1024
_TIMEOUT = 1800


class _FakeRequestRepo:
    def __init__(self, request: DownloadRequest) -> None:
        self._request = request

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return self._request if request_id == self._request.id else None

    async def update(self, request: DownloadRequest) -> None:
        pass


class _FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user if user_id == self._user.id else None


class _FakeStorage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path(f"/tmp/fake/{request_id}")


class _FakeNotifier:
    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        pass

    async def send_text(self, telegram_id: int, text: str) -> None:
        pass


class _FakeErrorLocalizer:
    def localize(self, error_key: str, locale: str | None = None, **kwargs: object) -> str:
        return error_key


class _CapturingProgressPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int, int, str | None, DownloadProgress]] = []

    async def publish(
        self,
        request_id: UUID,
        chat_id: int,
        message_id: int,
        language: str | None,
        progress: DownloadProgress,
    ) -> None:
        self.calls.append((request_id, chat_id, message_id, language, progress))


class _ProgressEmittingDownloader:
    """Real DownloaderPort shape: actually invokes progress_callback
    during the (fake) download, exactly like YtDlpDownloader would."""

    def __init__(self, progress_events: list[DownloadProgress], result_path: Path) -> None:
        self._progress_events = progress_events
        self._result_path = result_path

    async def get_preview(self, url: str):  # pragma: no cover — not exercised here
        raise NotImplementedError

    async def download(
        self, url: str, options: DownloadOptions, progress_callback=None
    ) -> DownloadResult:
        if progress_callback is not None:
            for event in self._progress_events:
                await progress_callback(event)
        return DownloadResult(self._result_path)


@pytest.mark.asyncio
async def test_progress_events_are_published_with_correct_coordinates_and_language() -> None:
    user = User.create_from_telegram(telegram_id=555, language="ru")
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")

    events = [
        DownloadProgress(percent=10.0, downloaded_bytes=100, total_bytes=1000, speed=50.0, eta=18),
        DownloadProgress(percent=50.0, downloaded_bytes=500, total_bytes=1000, speed=60.0, eta=8),
    ]
    publisher = _CapturingProgressPublisher()
    downloader = _ProgressEmittingDownloader(events, result_path=Path("/tmp/fake/video.mp4"))

    use_case = ProcessDownloadUseCase(
        download_request_repository=_FakeRequestRepo(request),
        user_repository=_FakeUserRepo(user),
        downloader=downloader,
        storage=_FakeStorage(),
        notifier=_FakeNotifier(),
        error_localizer=_FakeErrorLocalizer(),
        progress_publisher=publisher,
        max_deliverable_file_size_bytes=_MAX_BYTES,
        download_timeout_seconds=_TIMEOUT,
    )

    await use_case.execute(request.id, chat_id=777, message_id=888)

    assert len(publisher.calls) == 2
    for (req_id, chat_id, message_id, language, progress), expected in zip(
        publisher.calls, events, strict=True
    ):
        assert req_id == request.id
        assert chat_id == 777
        assert message_id == 888
        assert language == "ru"
        assert progress == expected


@pytest.mark.asyncio
async def test_no_progress_events_means_no_publish_calls() -> None:
    user = User.create_from_telegram(telegram_id=1)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")
    publisher = _CapturingProgressPublisher()
    downloader = _ProgressEmittingDownloader([], result_path=Path("/tmp/fake/video.mp4"))

    use_case = ProcessDownloadUseCase(
        download_request_repository=_FakeRequestRepo(request),
        user_repository=_FakeUserRepo(user),
        downloader=downloader,
        storage=_FakeStorage(),
        notifier=_FakeNotifier(),
        error_localizer=_FakeErrorLocalizer(),
        progress_publisher=publisher,
        max_deliverable_file_size_bytes=_MAX_BYTES,
        download_timeout_seconds=_TIMEOUT,
    )

    await use_case.execute(request.id, chat_id=1, message_id=2)

    assert publisher.calls == []
