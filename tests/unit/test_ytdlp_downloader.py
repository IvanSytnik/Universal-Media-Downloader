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

Day 11A: ``_run_download_in_process`` gained a fifth positional argument
(``format_kind_value``) so the download can be video or audio. The four
monkeypatched stand-ins below accept it and ignore it — they exercise
``download()``'s exception mapping, which is independent of the format.

Day 11B: ``_run_download_in_process`` gained a sixth positional argument
(``progress_sink``) for the progress bridge — same four stand-ins updated
again, same reasoning (they test exception mapping, which doesn't depend
on progress reporting). New tests below cover ``_build_download_progress``
and the progress_callback → progress_sink wiring itself, capturing actual
arguments rather than asserting a bare mock was called (lesson 11A.1).

Day 11C stage 1: ``_run_download_in_process`` gained a seventh positional
argument (``max_height``) — the same stand-ins updated once more, plus a
dedicated argument-capture test that the value actually reaches it
(lesson 11A.1: a plumbing parameter nobody asserts on is a parameter that
can silently stop being forwarded).
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
from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.progress_phase import ProgressPhase
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

    def _fake_run(
        url,
        output_dir,
        max_filesize_bytes,
        timeout_seconds,
        format_kind_value,
        progress_sink,
        max_height,
    ):
        return expected_path

    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", _fake_run)

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    result = await downloader.download("https://example.com/video", options)

    assert result == Path(expected_path)


@pytest.mark.asyncio
async def test_download_maps_timeout_to_timeout_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def _raise_timeout(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        progress_sink: object,
        max_height: int,
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
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        progress_sink: object,
        max_height: int,
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
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        progress_sink: object,
        max_height: int,
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


# --- Day 11B: progress -------------------------------------------------------


def test_build_download_progress_computes_percent_from_bytes() -> None:
    progress = ytdlp_downloader._build_download_progress(
        {"downloaded_bytes": 50, "total_bytes": 200, "speed": 1024.0, "eta": 30}
    )
    assert progress.percent == 25.0
    assert progress.downloaded_bytes == 50
    assert progress.total_bytes == 200
    assert progress.speed == 1024.0
    assert progress.eta == 30


def test_build_download_progress_percent_none_without_total() -> None:
    # Streams yt-dlp can't size up front — percent must stay None, not 0
    # or an exception, so callers know to render bytes/speed instead.
    progress = ytdlp_downloader._build_download_progress(
        {"downloaded_bytes": 1234, "total_bytes": None, "speed": None, "eta": None}
    )
    assert progress.percent is None
    assert progress.downloaded_bytes == 1234
    assert progress.total_bytes is None
    assert progress.speed is None
    assert progress.eta is None


def test_build_download_progress_missing_downloaded_bytes_defaults_zero() -> None:
    progress = ytdlp_downloader._build_download_progress({})
    assert progress.downloaded_bytes == 0
    assert progress.percent is None


def test_build_download_progress_converting_marker_maps_to_converting_phase() -> None:
    progress = ytdlp_downloader._build_download_progress({"phase": ProgressPhase.CONVERTING})
    assert progress.phase is ProgressPhase.CONVERTING
    assert progress.percent is None
    assert progress.downloaded_bytes == 0
    assert progress.total_bytes is None
    assert progress.speed is None
    assert progress.eta is None


# --- Day 11B.1: download→postprocess boundary (audio-only "converting") -----


def test_translate_progress_status_finished_audio_emits_converting_marker() -> None:
    raw = ytdlp_downloader._translate_progress_status(
        {"status": "finished"}, FormatKind.AUDIO
    )
    assert raw == {"phase": ProgressPhase.CONVERTING}


def test_translate_progress_status_finished_video_emits_nothing() -> None:
    # No ffmpeg transcode step on the video path — nothing worth
    # announcing at this boundary.
    raw = ytdlp_downloader._translate_progress_status(
        {"status": "finished"}, FormatKind.VIDEO
    )
    assert raw is None


def test_translate_progress_status_downloading_unchanged_by_format_kind() -> None:
    status = {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100}
    audio_raw = ytdlp_downloader._translate_progress_status(status, FormatKind.AUDIO)
    video_raw = ytdlp_downloader._translate_progress_status(status, FormatKind.VIDEO)
    assert audio_raw == video_raw == {
        "downloaded_bytes": 10,
        "total_bytes": 100,
        "speed": None,
        "eta": None,
    }


def test_translate_progress_status_other_statuses_emit_nothing() -> None:
    assert ytdlp_downloader._translate_progress_status(
        {"status": "error"}, FormatKind.AUDIO
    ) is None


@pytest.mark.asyncio
async def test_download_wires_progress_callback_through_to_domain(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Captures the actual `progress_sink` download() builds and hands to
    `_run_download_in_process`, invokes it as production code would (from
    a real executor thread), and asserts the caller's async
    `progress_callback` eventually receives a correctly-built
    DownloadProgress — the full bridge, not a bare mock (lesson 11A.1).

    The fake mirrors the REAL `_run_download_in_process`'s contract:
    a final `progress_sink(None)` before returning, signalling "no more
    progress events" — required so `download()`'s drain_task actually
    completes (see `_drain_bridge`'s docstring for why this must come
    from the executor thread itself, not from `download()`).
    """
    expected_path = str(tmp_path / "video.mp4")
    captured_calls: list[DownloadProgress] = []

    async def _progress_callback(progress: DownloadProgress) -> None:
        captured_calls.append(progress)

    def _fake_run_download_in_process(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        progress_sink,
        max_height: int,
    ) -> str:
        assert progress_sink is not None
        progress_sink({"downloaded_bytes": 10, "total_bytes": 100, "speed": 5.0, "eta": 9})
        progress_sink(None)
        return expected_path

    monkeypatch.setattr(
        ytdlp_downloader, "_run_download_in_process", _fake_run_download_in_process
    )

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    result = await downloader.download(
        "https://example.com/video", options, progress_callback=_progress_callback
    )

    assert result == Path(expected_path)
    # No polling needed: download() only returns after drain_task itself
    # returns (awaited in its finally), which only happens once it has
    # processed the None stop marker — and every real item sent before
    # that marker (same thread, same call_soon_threadsafe channel) is
    # guaranteed to have been processed first.
    assert len(captured_calls) == 1
    assert captured_calls[0] == DownloadProgress(
        percent=10.0, downloaded_bytes=10, total_bytes=100, speed=5.0, eta=9
    )


@pytest.mark.asyncio
async def test_download_without_progress_callback_passes_none_sink(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    expected_path = str(tmp_path / "video.mp4")
    captured: dict[str, Any] = {}

    def _fake_run_download_in_process(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        progress_sink,
        max_height: int,
    ) -> str:
        captured["progress_sink"] = progress_sink
        return expected_path

    monkeypatch.setattr(
        ytdlp_downloader, "_run_download_in_process", _fake_run_download_in_process
    )

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    await downloader.download("https://example.com/video", options)

    assert captured["progress_sink"] is None


# --- Day 11C stage 1: quality plumbing ---------------------------------------


@pytest.mark.asyncio
async def test_download_forwards_default_max_height_to_child_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """`max_height` is a pass-through parameter with a default at every
    hop, which is exactly the kind of plumbing that can quietly stop
    being forwarded without any test failing (lesson 11A.1). So capture
    the actual argument `download()` passes, not just that it ran.

    Stage 1 has no user-facing choice yet — the value is the module
    default. Stage 2 changes only where it comes from.
    """
    expected_path = str(tmp_path / "video.mp4")
    captured: dict[str, Any] = {}

    def _fake_run_download_in_process(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        progress_sink,
        max_height: int,
    ) -> str:
        captured["max_height"] = max_height
        return expected_path

    monkeypatch.setattr(
        ytdlp_downloader, "_run_download_in_process", _fake_run_download_in_process
    )

    downloader = YtDlpDownloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    await downloader.download("https://example.com/video", options)

    assert captured["max_height"] == 720
    assert captured["max_height"] == ytdlp_downloader._DEFAULT_MAX_HEIGHT


def test_preview_opts_pin_no_player_client() -> None:
    """Same regression guard as the download path (see
    test_download_ydl_opts.py): the preview extractor must not pin a
    youtube client either — a stale one hides formats.
    """
    assert "extractor_args" not in ytdlp_downloader._YDL_OPTS_PREVIEW
