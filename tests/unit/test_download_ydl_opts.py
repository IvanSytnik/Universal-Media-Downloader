"""Day 11A: the video/audio split lives entirely in
``_build_download_ydl_opts``. These tests pin exactly what differs
between the two paths and — just as importantly — what must NOT differ
(retries, timeouts, the reliability options), so a future tweak to the
shared options can't silently apply to only one format.

Day 11C stage 1: they also pin the quality fix — the video selector asks
for separate avc1 video + m4a audio streams under a height cap, the
audio selector prefers a real audio-only track, and NEITHER path pins a
youtube ``player_client`` any more (the hardcoded one was the cause of
the 360p-only downloads, not a mitigation — see the module docstring of
ytdlp_downloader.py).
"""

from __future__ import annotations

from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind
from src.infrastructure.downloader.ytdlp_downloader import _build_download_ydl_opts


def _noop_hook(filename: str) -> None:  # pragma: no cover - passed through only
    pass


def test_video_opts_request_merged_avc1_capped_at_default_720() -> None:
    opts = _build_download_ydl_opts("/tmp/out", None, FormatKind.VIDEO, _noop_hook)
    assert opts["format"] == (
        "bestvideo[height<=720][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]"
        "/best[ext=mp4][height<=720]"
        "/best[ext=mp4]/best"
    )
    # The merge is what reassembles the separate streams the selector now
    # actually asks for.
    assert opts["merge_output_format"] == "mp4"
    assert "postprocessors" not in opts


def test_video_opts_respect_explicit_max_height_1080() -> None:
    opts = _build_download_ydl_opts("/tmp/out", None, FormatKind.VIDEO, _noop_hook, max_height=1080)
    assert opts["format"] == (
        "bestvideo[height<=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]"
        "/best[ext=mp4][height<=1080]"
        "/best[ext=mp4]/best"
    )
    assert opts["merge_output_format"] == "mp4"


def test_video_height_filter_differs_between_720_and_1080() -> None:
    """The cap must actually reach the selector — not be accepted and
    dropped somewhere in the plumbing."""
    opts_720 = _build_download_ydl_opts(
        "/tmp/out", None, FormatKind.VIDEO, _noop_hook, max_height=720
    )
    opts_1080 = _build_download_ydl_opts(
        "/tmp/out", None, FormatKind.VIDEO, _noop_hook, max_height=1080
    )
    assert opts_720["format"] != opts_1080["format"]
    assert "height<=720" in opts_720["format"]
    assert "1080" not in opts_720["format"]
    assert "height<=1080" in opts_1080["format"]


def test_audio_opts_extract_mp3() -> None:
    opts = _build_download_ydl_opts("/tmp/out", None, FormatKind.AUDIO, _noop_hook)
    # m4a first: a real audio-only track, rather than a full muxed stream
    # whose video half ffmpeg would just throw away.
    assert opts["format"] == "bestaudio[ext=m4a]/bestaudio/best"
    # No mp4 merge on the audio path.
    assert "merge_output_format" not in opts
    pp = opts["postprocessors"]
    assert pp[0]["key"] == "FFmpegExtractAudio"
    assert pp[0]["preferredcodec"] == "mp3"


def test_audio_ignores_max_height() -> None:
    """There is no video stream on the audio path, so the cap must not
    leak into its selector at all."""
    opts_720 = _build_download_ydl_opts(
        "/tmp/out", None, FormatKind.AUDIO, _noop_hook, max_height=720
    )
    opts_1080 = _build_download_ydl_opts(
        "/tmp/out", None, FormatKind.AUDIO, _noop_hook, max_height=1080
    )
    assert opts_720["format"] == opts_1080["format"]
    assert "height" not in opts_720["format"]


def test_no_hardcoded_player_client_on_either_path() -> None:
    """Regression guard for Day 11C stage 1: pinning a youtube
    player_client is what limited every download to 360p. yt-dlp's own
    client selection is what keeps up with YouTube — a stale hardcoded
    one is worse than none.
    """
    for fk in (FormatKind.VIDEO, FormatKind.AUDIO):
        opts = _build_download_ydl_opts("/tmp/out", None, fk, _noop_hook)
        assert "extractor_args" not in opts


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


# --- Day 11C stage 3: the tier is what determines the cap ---------------------


def test_selector_height_comes_from_the_quality_tier() -> None:
    """End of the chain: whatever QualityKind.max_height says must be the
    number in the yt-dlp selector. Written against the enum rather than
    literal 720/1080 so that changing a tier's height can never leave
    this test asserting a stale number."""
    for quality in QualityKind:
        opts = _build_download_ydl_opts(
            "/tmp/out", None, FormatKind.VIDEO, _noop_hook, max_height=quality.max_height
        )
        assert f"height<={quality.max_height}" in opts["format"]


def test_the_two_tiers_produce_different_selectors() -> None:
    # Guards the degenerate pass: if both tiers resolved to one height,
    # every per-tier assertion above would still hold.
    opts_720 = _build_download_ydl_opts(
        "/tmp/out",
        None,
        FormatKind.VIDEO,
        _noop_hook,
        max_height=QualityKind.HD_720.max_height,
    )
    opts_1080 = _build_download_ydl_opts(
        "/tmp/out",
        None,
        FormatKind.VIDEO,
        _noop_hook,
        max_height=QualityKind.HD_1080.max_height,
    )
    assert opts_720["format"] != opts_1080["format"]


def test_audio_selector_ignores_the_tier_entirely() -> None:
    """mp3 has no video stream to cap — the audio branch must produce the
    identical selector at either tier (the DB column carries a tier for
    audio rows too; nothing may read it into the format string)."""
    opts_720 = _build_download_ydl_opts(
        "/tmp/out",
        None,
        FormatKind.AUDIO,
        _noop_hook,
        max_height=QualityKind.HD_720.max_height,
    )
    opts_1080 = _build_download_ydl_opts(
        "/tmp/out",
        None,
        FormatKind.AUDIO,
        _noop_hook,
        max_height=QualityKind.HD_1080.max_height,
    )
    assert opts_720["format"] == opts_1080["format"]
    assert "height" not in opts_720["format"]
