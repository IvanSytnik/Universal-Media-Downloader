"""YtDlpDownloader tests. The process runners (`_run_preview_in_process`,
`_run_download_in_process`) are monkeypatched so these tests never touch
the network or a real yt-dlp extraction — they check the adapter's own
logic: mapping yt-dlp's info dict to MediaPreview, media-type guessing,
and exception translation (yt_dlp exceptions must never leak past this
module — see module docstring in ytdlp_downloader.py).

Preview timeout: the preview extraction moved into a child process, so
patching `_extract_info_sync` in the test process no longer reaches it.
Preview stand-ins replace `_run_preview_in_process` instead (typed
against `RunPreviewInProcess`) and return what the child would send —
`_preview_facts(info)` — so the info → facts mapping is still exercised.
The child's own logic is tested by calling `_preview_worker_entrypoint`
in-process; the kill switch, against real processes, in
test_preview_kill_mechanism.py.

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

Day 11C (v2): ``_run_download_in_process`` takes the spec as two
primitives (``format_kind_value``, ``video_tier_value``) BEFORE
``progress_sink`` — the stand-ins mirror that order. A stand-in with the
old order silently receives the tier string as its sink and the
progress drain then waits forever, so keep them in step. Argument
capture pins that the primitives actually reach the runner (lesson
11A.1). Every stand-in is installed through ``_install_runner``, typed
against ``RunDownloadInProcess``, so mypy catches that drift (this file
is type-checked in the gate).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yt_dlp

from src.domain.exceptions import (
    DownloadTimeoutError,
    ExtractionError,
    FileTooLargeError,
    PreviewTimeoutError,
)
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.download_spec import (
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
    spec_from_parts,
    spec_kind,
)
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.progress_phase import ProgressPhase
from src.infrastructure.downloader import ytdlp_downloader
from src.infrastructure.downloader.ytdlp_downloader import (
    RunDownloadInProcess,
    RunPreviewInProcess,
    YtDlpDownloader,
)

_Sink = Callable[[dict[str, Any] | None], None] | None

_PREVIEW_TIMEOUT = 45


def _downloader() -> YtDlpDownloader:
    return YtDlpDownloader(preview_timeout_seconds=_PREVIEW_TIMEOUT)


def _install_runner(monkeypatch: pytest.MonkeyPatch, runner: RunDownloadInProcess) -> None:
    monkeypatch.setattr(ytdlp_downloader, "_run_download_in_process", runner)


def _install_preview_runner(monkeypatch: pytest.MonkeyPatch, runner: RunPreviewInProcess) -> None:
    monkeypatch.setattr(ytdlp_downloader, "_run_preview_in_process", runner)


def _install_preview_info(monkeypatch: pytest.MonkeyPatch, info: dict[str, Any] | None) -> None:
    """Stand-in for a child that extracted ``info`` (None: yt-dlp found
    nothing)."""

    def _run(url: str, timeout_seconds: int, /) -> dict[str, Any] | None:
        return ytdlp_downloader._preview_facts(info) if info is not None else None

    _install_preview_runner(monkeypatch, _run)


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
    _install_preview_info(monkeypatch, fake_info)

    downloader = _downloader()
    preview = await downloader.get_preview("https://example.com/video")

    assert preview.source_url == "https://example.com/video"
    assert preview.title == "Big Buck Bunny"
    assert preview.duration_seconds == 596
    assert preview.uploader == "Blender Foundation"
    assert preview.thumbnail_url == "https://example.com/thumb.jpg"
    assert preview.media_type == MediaType.VIDEO


@pytest.mark.asyncio
async def test_get_preview_falls_back_to_default_title(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_preview_info(monkeypatch, {})

    downloader = _downloader()
    preview = await downloader.get_preview("https://example.com/video")

    # No title is None here; the card's "Untitled" comes from the locale.
    assert preview.title is None
    assert preview.duration_seconds is None
    assert preview.media_type == MediaType.UNKNOWN


@pytest.mark.asyncio
async def test_get_preview_raises_extraction_error_on_none_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_preview_info(monkeypatch, None)

    downloader = _downloader()
    with pytest.raises(ExtractionError):
        await downloader.get_preview("https://example.com/video")


@pytest.mark.asyncio
async def test_get_preview_wraps_ytdlp_download_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url: str, timeout_seconds: int, /) -> dict[str, Any] | None:
        # What the runner raises when the child reported a yt-dlp
        # DownloadError with this message.
        raise ytdlp_downloader._DownloadExtractError("Video unavailable")

    _install_preview_runner(monkeypatch, _raise)

    downloader = _downloader()
    # "Video unavailable" classifies to ContentUnavailableError, an
    # ExtractionError subclass — still caught as ExtractionError.
    with pytest.raises(ExtractionError) as exc_info:
        await downloader.get_preview("https://example.com/private-video")
    # Categorized, and no raw yt-dlp text leaked to the user-facing str.
    assert exc_info.value.error_key == "error-unavailable"
    assert "Video unavailable" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_preview_passes_configured_timeout_to_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, int]] = []

    def _run(url: str, timeout_seconds: int, /) -> dict[str, Any] | None:
        seen.append((url, timeout_seconds))
        return ytdlp_downloader._preview_facts({"title": "t"})

    _install_preview_runner(monkeypatch, _run)

    await YtDlpDownloader(preview_timeout_seconds=7).get_preview("https://example.com/v")

    assert seen == [("https://example.com/v", 7)]


@pytest.mark.asyncio
async def test_get_preview_maps_timeout_to_preview_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(url: str, timeout_seconds: int, /) -> dict[str, Any] | None:
        raise ytdlp_downloader._PreviewTimeoutError("превысило лимит 45 секунд")

    _install_preview_runner(monkeypatch, _raise)

    with pytest.raises(PreviewTimeoutError) as exc_info:
        await _downloader().get_preview("https://example.com/video")
    # Its own key — "the download took too long" would be wrong here —
    # and still an ExtractionError, so every preview handler catches it.
    assert exc_info.value.error_key == "error-preview-timeout"
    assert isinstance(exc_info.value, ExtractionError)
    assert str(exc_info.value) == ""


@pytest.mark.asyncio
async def test_get_preview_maps_process_error_to_generic_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(url: str, timeout_seconds: int, /) -> dict[str, Any] | None:
        raise ytdlp_downloader._DownloadProcessError("RuntimeError: /secret/path")

    _install_preview_runner(monkeypatch, _raise)

    with pytest.raises(ExtractionError) as exc_info:
        await _downloader().get_preview("https://example.com/video")
    assert type(exc_info.value) is ExtractionError
    assert "/secret/path" not in str(exc_info.value)


class _ListQueue:
    """Stands in for the child's result queue when the entrypoint runs
    in-process."""

    def __init__(self) -> None:
        self.items: list[tuple[str, Any]] = []

    def put(self, item: tuple[str, Any]) -> None:
        self.items.append(item)


def _run_entrypoint(
    monkeypatch: pytest.MonkeyPatch, extract: Callable[[str], dict[str, Any] | None]
) -> list[tuple[str, Any]]:
    monkeypatch.setattr(ytdlp_downloader, "_extract_info_sync", extract)
    result_queue = _ListQueue()
    ytdlp_downloader._preview_worker_entrypoint("https://example.com/v", result_queue)  # type: ignore[arg-type]
    return result_queue.items


def test_preview_entrypoint_sends_facts_not_the_info_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info: dict[str, Any] = {
        "title": "t",
        "extractor_key": "Youtube",
        "vcodec": "avc1.640028",
        "formats": [{"vcodec": "avc1.640028", "width": 1920, "height": 1080}],
        "huge_field": "x" * 10_000,
    }

    items = _run_entrypoint(monkeypatch, lambda url: info)

    assert items == [
        (
            "ok",
            {
                "title": "t",
                "duration": None,
                "uploader": None,
                "thumbnail": None,
                "media_type": "video",
                "extractor_key": "youtube",
                "max_compatible_short_side": 1080,
            },
        )
    ]


def test_preview_entrypoint_reports_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_entrypoint(monkeypatch, lambda url: None) == [("empty", None)]


def test_preview_entrypoint_reports_ytdlp_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url: str) -> dict[str, Any] | None:
        raise yt_dlp.utils.DownloadError("ERROR: Private video")

    assert _run_entrypoint(monkeypatch, _raise) == [("extract_error", "ERROR: Private video")]


def test_preview_entrypoint_reports_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url: str) -> dict[str, Any] | None:
        raise KeyError("formats")

    assert _run_entrypoint(monkeypatch, _raise) == [("error", "KeyError: 'formats'")]


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
async def test_download_returns_path_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected_path = str(tmp_path / "video.mp4")

    def _fake_run(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        return DownloadResult(Path(expected_path))

    _install_runner(monkeypatch, _fake_run)

    downloader = _downloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    result = await downloader.download("https://example.com/video", options)

    assert result.path == Path(expected_path)


@pytest.mark.asyncio
async def test_download_maps_timeout_to_timeout_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise_timeout(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        raise ytdlp_downloader._DownloadTimeoutError("превысило лимит 1 секунд")

    _install_runner(monkeypatch, _raise_timeout)

    downloader = _downloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=1)

    # Day 10: timeout gets its own category + key. The user-facing text is
    # rendered from that key downstream (worker/presentation), NOT carried
    # in the exception — so str(exc) is empty here by design.
    with pytest.raises(DownloadTimeoutError) as exc_info:
        await downloader.download("https://example.com/video", options)
    assert exc_info.value.error_key == "error-timeout"


@pytest.mark.asyncio
async def test_download_maps_process_error_to_extraction_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise_process_error(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        # This diagnostic-rich message must NOT leak into the raised
        # exception's text (it may contain container paths, signed CDN
        # URLs, etc.) — it belongs in the log only.
        raise ytdlp_downloader._DownloadProcessError(
            "dir_contents=[...] info_summary={'url': 'https://signed.example/secret'}"
        )

    _install_runner(monkeypatch, _raise_process_error)

    downloader = _downloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)

    with pytest.raises(ExtractionError) as exc_info:
        await downloader.download("https://example.com/video", options)

    # A generic process error falls back to the generic extraction key,
    # and crucially leaks no diagnostic text.
    assert exc_info.value.error_key == "error-extraction-failed"
    assert "signed.example" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_download_maps_file_too_large_to_categorized_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _raise_too_large(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        # Day 10: the internal error carries the numbers, not a pre-baked
        # (hardcoded-language) sentence.
        raise ytdlp_downloader._FileTooLargeError(estimated_mb=178, limit_mb=50)

    _install_runner(monkeypatch, _raise_too_large)

    downloader = _downloader()
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
    raw = ytdlp_downloader._translate_progress_status({"status": "finished"}, FormatKind.AUDIO)
    assert raw == {"phase": ProgressPhase.CONVERTING}


def test_translate_progress_status_finished_video_emits_nothing() -> None:
    # No ffmpeg transcode step on the video path — nothing worth
    # announcing at this boundary.
    raw = ytdlp_downloader._translate_progress_status({"status": "finished"}, FormatKind.VIDEO)
    assert raw is None


def test_translate_progress_status_downloading_unchanged_by_format_kind() -> None:
    status = {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100}
    audio_raw = ytdlp_downloader._translate_progress_status(status, FormatKind.AUDIO)
    video_raw = ytdlp_downloader._translate_progress_status(status, FormatKind.VIDEO)
    assert (
        audio_raw
        == video_raw
        == {
            "downloaded_bytes": 10,
            "total_bytes": 100,
            "speed": None,
            "eta": None,
        }
    )


def test_translate_progress_status_other_statuses_emit_nothing() -> None:
    assert (
        ytdlp_downloader._translate_progress_status({"status": "error"}, FormatKind.AUDIO) is None
    )


@pytest.mark.asyncio
async def test_download_wires_progress_callback_through_to_domain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        assert progress_sink is not None
        progress_sink({"downloaded_bytes": 10, "total_bytes": 100, "speed": 5.0, "eta": 9})
        progress_sink(None)
        return DownloadResult(Path(expected_path))

    _install_runner(monkeypatch, _fake_run_download_in_process)

    downloader = _downloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    result = await downloader.download(
        "https://example.com/video", options, progress_callback=_progress_callback
    )

    assert result.path == Path(expected_path)
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected_path = str(tmp_path / "video.mp4")
    captured: dict[str, Any] = {}

    def _fake_run_download_in_process(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        captured["progress_sink"] = progress_sink
        return DownloadResult(Path(expected_path))

    _install_runner(monkeypatch, _fake_run_download_in_process)

    downloader = _downloader()
    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60)
    await downloader.download("https://example.com/video", options)

    assert captured["progress_sink"] is None


# --- Day 11C (v2): the spec crosses the spawn boundary as primitives -------


def _capturing_runner(captured: dict[str, Any], result: str) -> Any:
    def _fake_run_download_in_process(
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: _Sink = None,
    ) -> DownloadResult:
        captured["format_kind_value"] = format_kind_value
        captured["video_tier_value"] = video_tier_value
        return DownloadResult(Path(result))

    return _fake_run_download_in_process


@pytest.mark.parametrize(
    ("spec", "kind", "tier"),
    [
        (VideoSpec(VideoTier.P720), "video", "p720"),
        (VideoSpec(VideoTier.P1080), "video", "p1080"),
        (VideoSpec(VideoTier.BEST), "video", "best"),
        (AudioSpec(), "audio", None),
    ],
)
@pytest.mark.asyncio
async def test_download_forwards_spec_primitives_to_child_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    spec: DownloadSpec,
    kind: str,
    tier: str | None,
) -> None:
    """The READ link at the process boundary (lesson 11A.1): what crosses
    into the child must come from `options.spec`, for every shape — a
    test that only checked the 720p default would pass against a
    downloader that ignored `options` entirely.
    """
    captured: dict[str, Any] = {}
    _install_runner(monkeypatch, _capturing_runner(captured, str(tmp_path / "out")))

    options = DownloadOptions(output_dir=tmp_path, timeout_seconds=60, spec=spec)
    await _downloader().download("https://example.com/video", options)

    assert captured == {"format_kind_value": kind, "video_tier_value": tier}
    # Plain str/None (pickle-safe under spawn), never the dataclass/enum.
    assert type(captured["format_kind_value"]) is str
    assert captured["video_tier_value"] is None or type(captured["video_tier_value"]) is str


@pytest.mark.parametrize(
    "spec",
    [VideoSpec(VideoTier.P720), VideoSpec(VideoTier.P1080), VideoSpec(VideoTier.BEST), AudioSpec()],
)
def test_child_rebuilds_the_same_ydl_opts_from_the_primitives(spec: DownloadSpec) -> None:
    """Parent→child round trip: the primitives the parent sends rebuild a
    spec that yields byte-identical selection options in the child."""
    rebuilt = spec_from_parts(spec_kind(spec).value, ytdlp_downloader._video_tier_value(spec))
    assert rebuilt == spec

    def _hook(_: str) -> None:  # pragma: no cover - never invoked
        pass

    keys = ("format", "format_sort", "merge_output_format", "postprocessors")
    original = ytdlp_downloader._build_download_ydl_opts("/o", None, spec, _hook)
    child = ytdlp_downloader._build_download_ydl_opts("/o", None, rebuilt, _hook)
    assert {k: original.get(k) for k in keys} == {k: child.get(k) for k in keys}


@pytest.mark.asyncio
async def test_preview_maps_extractor_key_and_compatible_short_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    info = {
        "title": "t",
        "extractor_key": "TikTok",
        "vcodec": "h264",
        "formats": [
            {"vcodec": "h264", "acodec": "aac", "width": 720, "height": 1280},
            {"vcodec": "h265", "acodec": "none", "width": 1080, "height": 1920},
        ],
    }
    _install_preview_info(monkeypatch, info)

    preview = await _downloader().get_preview("https://tiktok.com/@a/video/1")

    assert preview.extractor_key == "tiktok"
    # 1080 exists only in h265; the compatible (h264) top is 720.
    assert preview.max_compatible_short_side == 720


def test_preview_opts_pin_no_player_client() -> None:
    """Same regression guard as the download path (see
    test_download_ydl_opts.py): the preview extractor must not pin a
    youtube client either — a stale one hides formats.
    """
    assert "extractor_args" not in ytdlp_downloader._YDL_OPTS_PREVIEW
