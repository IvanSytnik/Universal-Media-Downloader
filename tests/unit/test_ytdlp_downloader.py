"""YtDlpDownloader tests. `_extract_info_sync` is monkeypatched so these
tests never touch the network or a real yt-dlp extraction — they check
the adapter's own logic: mapping yt-dlp's info dict to MediaPreview,
media-type guessing, and exception translation (yt_dlp exceptions must
never leak past this module — see module docstring in ytdlp_downloader.py).

Day 10: exception translation now produces CATEGORIZED domain errors
carrying a semantic ``error_key`` instead of a user-facing text string.
The raw yt-dlp/diagnostic text goes to the LOG only (bug #6), so the
raised exception's ``str()`` is intentionally empty — tests assert on the
exception TYPE and ``error_key``, not on message text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yt_dlp

from src.domain.exceptions import (
    DownloadTimeoutError,
    ExtractionError,
    FileTooLargeError,
)
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.enums import MediaType
from src.infrastructure.downloader import ytdlp_downloader
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader


@pytest.mark.asyncio
async def test_get_preview_maps_info_dict_to_media_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_info: dict[str, Any] = {
        "title": "Big Buck Bunny",
        "duration": 596,
        "uploader": "Blender Foundation",
        "thumbnail": "https://example.com/thumb.jpg",
        "vcodec": "h264",
        "acodec": "aac",
    }
    monkeypatch.setattr(ytdlp_downloader, "_extract_info_sync", lambda url: fake_info)

    downloader = YtDlpDownloader()
    preview = await downloader.get_preview("https://example.com/video")

    assert preview.source_url == "https://example.com/video"
    assert preview.title == "Big Buck Bunny"
    assert preview.duration_seconds == 596
    assert preview.uploader == "Blender Foundation"
    assert preview.thumbnail_url == "https://example.com/thumb.jpg"
    assert preview.media_type == MediaType.VIDEO


@pytest.mark.asyncio
async def test_get_preview_falls_back_to_default_title(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ytdlp_downloader, "_extract_info_sync", lambda url: {})

    downloader = YtDlpDownloader()
    preview = await downloader.get_preview("https://example.com/video")

    assert preview.title == "Без названия"
    assert preview.duration_seconds is None
    assert preview.media_type == MediaType.UNKNOWN


@pytest.mark.asyncio
async def test_get_preview_raises_extraction_error_on_none_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ytdlp_downloader, "_extract_info_sync", lambda url: None)

    downloader = YtDlpDownloader()
    with pytest.raises(ExtractionError):
        await downloader.get_preview("https://example.com/video")


@pytest.mark.asyncio
async def test_get_preview_wraps_ytdlp_download_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url: str) -> dict[str, Any]:
        raise yt_dlp.utils.DownloadError("Video unavailable")

    monkeypatch.setattr(ytdlp_downloader, "_extract_info_sync", _raise)

    downloader = YtDlpDownloader()
    # "Video unavailable" classifies to ContentUnavailableError, an
    # ExtractionError subclass — still caught as ExtractionError.
    with pytest.raises(ExtractionError) as exc_info:
        await downloader.get_preview("https://example.com/private-video")
    # Categorized, and no raw yt-dlp text leaked to the user-facing str.
    assert exc_info.value.error_key == "error-unavailable"
    assert "Video unavailable" not in str(exc_info.value)


def test_guess_media_type_video() -> None:
    info = {"vcodec": "h264", "acodec": "aac"}
    assert ytdlp_downloader._guess_media_type(info) == MediaType.VIDEO


def test_guess_media_type_audio_only() -> None:
    info = {"vcodec": "none", "acodec": "mp3"}
    assert ytdlp_downloader._guess_media_type(info) == MediaType.AUDIO


def test_guess_media_type_unknown() -> None:
    info = {"vcodec": "none", "acodec": "none"}
    assert ytdlp_downloader._guess_media_type(info) == MediaType.UNKNOWN


@pytest.mark.asyncio
async def test_download_returns_path_on_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    expected_path = str(tmp_path / "video.mp4")
    monkeypatch.setattr(
        ytdlp_downloader,
        "_run_download_in_process",
        lambda url, output_dir, max_filesize_bytes, timeout_seconds: expected_path,
    )

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    result = await downloader.download("https://example.com/video", options)

    assert result == Path(expected_path)


@pytest.mark.asyncio
async def test_download_maps_timeout_to_timeout_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _raise_timeout(
        url: str, output_dir: str, max_filesize_bytes: int | None, timeout_seconds: int
    ) -> str:
        raise ytdlp_downloader._DownloadTimeoutError("превысило лимит 1 секунд")

    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", _raise_timeout)

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=1)

    # Day 10: timeout gets its own category + key. The user-facing text is
    # rendered from that key downstream (worker/presentation), NOT carried
    # in the exception — so str(exc) is empty here by design.
    with pytest.raises(DownloadTimeoutError) as exc_info:
        await downloader.download("https://example.com/video", options)
    assert exc_info.value.error_key == "error-timeout"


@pytest.mark.asyncio
async def test_download_maps_process_error_to_extraction_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _raise_process_error(
        url: str, output_dir: str, max_filesize_bytes: int | None, timeout_seconds: int
    ) -> str:
        # This diagnostic-rich message must NOT leak into the raised
        # exception's text (it may contain container paths, signed CDN
        # URLs, etc.) — it belongs in the log only.
        raise ytdlp_downloader._DownloadProcessError(
            "dir_contents=[...] info_summary={'url': 'https://signed.example/secret'}"
        )

    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", _raise_process_error)

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)

    with pytest.raises(ExtractionError) as exc_info:
        await downloader.download("https://example.com/video", options)

    # A generic process error falls back to the generic extraction key,
    # and crucially leaks no diagnostic text.
    assert exc_info.value.error_key == "error-extraction-failed"
    assert "signed.example" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_download_maps_file_too_large_to_categorized_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _raise_too_large(
        url: str, output_dir: str, max_filesize_bytes: int | None, timeout_seconds: int
    ) -> str:
        # Day 10: the internal error carries the numbers, not a pre-baked
        # (hardcoded-language) sentence.
        raise ytdlp_downloader._FileTooLargeError(estimated_mb=178, limit_mb=50)

    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", _raise_too_large)

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)

    with pytest.raises(FileTooLargeError) as exc_info:
        await downloader.download("https://example.com/video", options)
    # The numbers survive as structured data for localized rendering.
    assert exc_info.value.error_key == "error-too-large"
    assert exc_info.value.estimated_mb == 178
    assert exc_info.value.limit_mb == 50
