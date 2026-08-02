"""Day 11A: the video/audio split lives entirely in
``_build_download_ydl_opts``. These tests pin exactly what differs
between the two paths and — just as importantly — what must NOT differ
(retries, timeouts, the reliability options), so a future tweak to the
shared options can't silently apply to only one format.
"""

from __future__ import annotations

from src.domain.value_objects.format_kind import FormatKind
from src.infrastructure.downloader.ytdlp_downloader import _build_download_ydl_opts


def _noop_hook(filename: str) -> None:  # pragma: no cover - passed through only
    pass


def test_video_opts_unchanged_from_pre_day11() -> None:
    opts = _build_download_ydl_opts("/tmp/out", None, FormatKind.VIDEO, _noop_hook)
    assert opts["format"] == "best[ext=mp4]/best"
    assert opts["merge_output_format"] == "mp4"
    assert "postprocessors" not in opts


def test_audio_opts_extract_mp3() -> None:
    opts = _build_download_ydl_opts("/tmp/out", None, FormatKind.AUDIO, _noop_hook)
    assert opts["format"] == "bestaudio/best"
    # No mp4 merge on the audio path.
    assert "merge_output_format" not in opts
    pp = opts["postprocessors"]
    assert pp[0]["key"] == "FFmpegExtractAudio"
    assert pp[0]["preferredcodec"] == "mp3"


def test_shared_reliability_options_identical_across_formats() -> None:
    video = _build_download_ydl_opts("/tmp/out", None, FormatKind.VIDEO, _noop_hook)
    audio = _build_download_ydl_opts("/tmp/out", None, FormatKind.AUDIO, _noop_hook)
    for key in (
        "retries",
        "fragment_retries",
        "socket_timeout",
        "continuedl",
        "restrictfilenames",
        "noplaylist",
        "outtmpl",
        "extractor_args",
        "post_hooks",
    ):
        assert video[key] == audio[key], f"shared option diverged: {key}"


def test_max_filesize_backstop_applied_on_both_paths() -> None:
    for fk in (FormatKind.VIDEO, FormatKind.AUDIO):
        opts = _build_download_ydl_opts("/tmp/out", 5_000_000, fk, _noop_hook)
        assert opts["max_filesize"] == 5_000_000


def test_no_max_filesize_key_when_unset() -> None:
    opts = _build_download_ydl_opts("/tmp/out", None, FormatKind.VIDEO, _noop_hook)
    assert "max_filesize" not in opts
