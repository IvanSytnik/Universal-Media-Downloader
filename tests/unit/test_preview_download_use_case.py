"""PreviewDownloadUseCase tests using a fake DownloaderPort — no yt-dlp,
no network at all.
"""

from __future__ import annotations

import pytest

from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.domain.exceptions import ExtractionError, UnsupportedURLError
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview


class FakeDownloader:
    def __init__(self, preview: MediaPreview | None = None, error: Exception | None = None) -> None:
        self._preview = preview
        self._error = error
        self.requested_urls: list[str] = []

    async def get_preview(self, url: str) -> MediaPreview:
        self.requested_urls.append(url)
        if self._error is not None:
            raise self._error
        assert self._preview is not None
        return self._preview


@pytest.mark.asyncio
async def test_returns_preview_for_valid_url() -> None:
    expected = MediaPreview(
        source_url="https://example.com/video",
        title="Test Video",
        duration_seconds=125,
        uploader="Test Channel",
        thumbnail_url="https://example.com/thumb.jpg",
        media_type=MediaType.VIDEO,
    )
    downloader = FakeDownloader(preview=expected)
    use_case = PreviewDownloadUseCase(downloader)

    result = await use_case.execute("https://example.com/video")

    assert result == expected
    assert downloader.requested_urls == ["https://example.com/video"]


@pytest.mark.asyncio
async def test_rejects_malformed_url_before_calling_downloader() -> None:
    downloader = FakeDownloader(preview=None)
    use_case = PreviewDownloadUseCase(downloader)

    with pytest.raises(UnsupportedURLError):
        await use_case.execute("not-a-url")

    # The downloader must never be called for a URL that fails
    # validation — this is what makes validation "the first line of
    # defense" rather than decorative.
    assert downloader.requested_urls == []


@pytest.mark.asyncio
async def test_propagates_extraction_error_from_downloader() -> None:
    downloader = FakeDownloader(error=ExtractionError("video unavailable"))
    use_case = PreviewDownloadUseCase(downloader)

    with pytest.raises(ExtractionError):
        await use_case.execute("https://example.com/private-video")
