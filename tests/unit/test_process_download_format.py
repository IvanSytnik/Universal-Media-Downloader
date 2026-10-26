"""Day 11A.1 regression guard: ProcessDownloadUseCase must thread the
request's ``format_kind`` into the ``DownloadOptions`` it hands the
downloader.

This is the test that was missing in 11A. The format was persisted on
the request correctly, but the worker built ``DownloadOptions`` without
it, so the VIDEO default always won and tapping MP3 delivered video. The
existing use-case tests mocked the downloader without inspecting the
options, so nothing caught it. This fake CAPTURES the options and asserts
on the format for both video and audio (since Day 11C v2 carried as
``DownloadOptions.spec``; every tier is covered in
test_process_download_spec.py).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.download_spec import AudioSpec, VideoSpec, VideoTier


class _CapturingDownloader:
    """Records the DownloadOptions it was called with, returns a dummy
    path so the use case proceeds to (a stubbed) delivery."""

    def __init__(self) -> None:
        self.captured_options: DownloadOptions | None = None

    async def get_preview(self, url: str):  # pragma: no cover - unused here
        raise NotImplementedError

    async def download(
        self, url: str, options: DownloadOptions, progress_callback=None
    ) -> DownloadResult:
        self.captured_options = options
        return DownloadResult(Path("/tmp/out.bin"))


class _FakeRequestRepo:
    def __init__(self, request: DownloadRequest) -> None:
        self._request = request

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return self._request

    async def claim_for_processing(self, request_id: UUID) -> bool:
        return True

    async def update(self, request: DownloadRequest) -> None:
        return None


class _FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user


class _FakeStorage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path("/tmp") / str(request_id)

    async def release(self, request_id: UUID) -> None:
        return None

    async def available_bytes(self) -> int:
        return 10**12


class _FakeNotifier:
    async def send_file(self, telegram_id: int, media: DeliverableMedia, caption=None) -> None:
        return None

    async def send_text(self, telegram_id: int, text: str) -> None:  # pragma: no cover
        return None


class _FakeErrorLocalizer:
    def localize(self, error_key: str, locale, **kwargs) -> str:  # pragma: no cover
        return error_key


class _NoopProgressPublisher:
    async def publish(self, request_id, chat_id, message_id, language, progress) -> None:
        pass


def _make_use_case(request: DownloadRequest, downloader: _CapturingDownloader):
    user = User(id=request.user_id, telegram_id=555)
    return ProcessDownloadUseCase(
        download_request_repository=_FakeRequestRepo(request),
        user_repository=_FakeUserRepo(user),
        downloader=downloader,
        storage=_FakeStorage(),
        notifier=_FakeNotifier(),
        error_localizer=_FakeErrorLocalizer(),
        progress_publisher=_NoopProgressPublisher(),
        max_deliverable_file_size_bytes=50 * 1024 * 1024,
        download_timeout_seconds=1800,
        min_free_disk_bytes=0,
    )


@pytest.mark.asyncio
async def test_audio_request_passes_audio_to_downloader() -> None:
    request = DownloadRequest.create(
        user_id=uuid4(),
        source_url="https://youtube.com/watch?v=x",
        spec=AudioSpec(),
    )
    downloader = _CapturingDownloader()
    await _make_use_case(request, downloader).execute(request.id, chat_id=1, message_id=2)

    assert downloader.captured_options is not None
    assert downloader.captured_options.spec == AudioSpec()


@pytest.mark.asyncio
async def test_video_request_passes_video_to_downloader() -> None:
    request = DownloadRequest.create(
        user_id=uuid4(),
        source_url="https://youtube.com/watch?v=x",
        spec=VideoSpec(VideoTier.P720),
    )
    downloader = _CapturingDownloader()
    await _make_use_case(request, downloader).execute(request.id, chat_id=1, message_id=2)

    assert downloader.captured_options is not None
    assert downloader.captured_options.spec == VideoSpec(VideoTier.P720)
