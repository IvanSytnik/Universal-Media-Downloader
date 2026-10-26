"""Day 11C — the READ link for the request's DownloadSpec (lesson 11A.1).

This is the test that did not exist for ``format_kind`` in 11A, which is
exactly why the MP3 button shipped delivering video: the field was
persisted correctly, the worker built ``DownloadOptions`` without it, the
VIDEO default won, and every existing use-case test mocked the downloader
without ever looking at the options it received.

So the downloader fake here CAPTURES the options and the assertions are
on what it captured. Every spec shape is checked, including the
non-default ones — a test that only ever asserted the 720p default would
pass against a hardcoded default just as happily as against real
plumbing.
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
from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)


class _CapturingDownloader:
    def __init__(self) -> None:
        self.captured_options: DownloadOptions | None = None

    async def get_preview(self, url: str) -> object:  # pragma: no cover - unused
        raise NotImplementedError

    async def download(
        self, url: str, options: DownloadOptions, progress_callback: object = None
    ) -> DownloadResult:
        self.captured_options = options
        return DownloadResult(Path("/tmp/out.bin"))


class _FakeRequestRepo:
    def __init__(self, request: DownloadRequest) -> None:
        self._request = request

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return self._request

    async def update(self, request: DownloadRequest) -> None:
        return None

    async def mark_failed_by_id(self, request_id: UUID) -> None:  # pragma: no cover
        return None


class _FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user


class _Storage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path("/tmp/umd-test")

    async def cleanup_expired(self, max_age_seconds: int) -> int:  # pragma: no cover
        return 0


class _Notifier:
    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        return None

    async def send_text(self, telegram_id: int, text: str) -> None:  # pragma: no cover
        return None


class _Localizer:
    def localize(self, error_key: str, locale: str | None = None, **kwargs: object) -> str:
        return error_key  # pragma: no cover - no failure path here


class _NoopPublisher:
    async def publish(self, *args: object, **kwargs: object) -> None:
        return None


async def _capture(spec: DownloadSpec) -> DownloadOptions:
    user = User(id=uuid4(), telegram_id=42)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v", spec=spec)
    downloader = _CapturingDownloader()

    use_case = ProcessDownloadUseCase(
        download_request_repository=_FakeRequestRepo(request),
        user_repository=_FakeUserRepo(user),
        downloader=downloader,
        storage=_Storage(),
        notifier=_Notifier(),
        error_localizer=_Localizer(),
        progress_publisher=_NoopPublisher(),
        max_deliverable_file_size_bytes=2000 * 1024 * 1024,
        download_timeout_seconds=1800,
    )
    await use_case.execute(request.id, chat_id=1, message_id=2)

    assert downloader.captured_options is not None
    return downloader.captured_options


@pytest.mark.parametrize(
    "spec",
    [
        VideoSpec(VideoTier.P720),
        VideoSpec(VideoTier.P1080),
        VideoSpec(VideoTier.BEST),
        AudioSpec(),
    ],
)
@pytest.mark.asyncio
async def test_persisted_spec_reaches_download_options(spec: DownloadSpec) -> None:
    options = await _capture(spec)
    assert options.spec == spec


@pytest.mark.parametrize(
    "spec", [VideoSpec(VideoTier.P1080), VideoSpec(VideoTier.BEST), AudioSpec()]
)
@pytest.mark.asyncio
async def test_non_default_spec_is_not_silently_replaced_by_the_default(
    spec: DownloadSpec,
) -> None:
    # The specific 11A.1 failure shape: plumbing missing, default wins,
    # nothing looks wrong. Asserting a non-default spec survives is what
    # makes this test able to fail.
    options = await _capture(spec)
    assert options.spec != DEFAULT_DOWNLOAD_SPEC
