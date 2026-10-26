"""Day 11A: the video/audio split lives entirely in
``_build_download_ydl_opts``. These tests pin exactly what differs
between the two paths and — just as importantly — what must NOT differ
(retries, timeouts, the reliability options), so a future tweak to the
shared options can't silently apply to only one format.

Day 11C stage 1: NEITHER path pins a youtube ``player_client`` (the
hardcoded one was the cause of the 360p-only downloads, not a
mitigation — see the module docstring of ytdlp_downloader.py).

Day 11C (v2): video quality is a format SORT on the tier's short side
(``res:``), not a height filter, and the compatible codec is one
constant shared with the preview's short-side calculation. What the
sort actually SELECTS on real format lists is pinned separately, on the
Stage 0 fixtures, in test_format_selection_fixtures.py.
"""

from __future__ import annotations

import pytest

from src.domain.value_objects.download_spec import (
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)
from src.infrastructure.downloader import ytdlp_downloader
from src.infrastructure.downloader.ytdlp_downloader import (
    _build_download_ydl_opts,
    _max_compatible_short_side,
)

_BOTH: list[DownloadSpec] = [VideoSpec(VideoTier.P720), AudioSpec()]


def _noop_hook(filename: str) -> None:  # pragma: no cover - passed through only
    pass


def _opts(spec: DownloadSpec, max_filesize: int | None = None) -> dict[str, object]:
    return _build_download_ydl_opts("/tmp/out", max_filesize, spec, _noop_hook)


@pytest.mark.parametrize(
    ("tier", "res"),
    [(VideoTier.P720, "res:720"), (VideoTier.P1080, "res:1080")],
)
def test_video_sorts_by_the_tiers_short_side(tier: VideoTier, res: str) -> None:
    opts = _opts(VideoSpec(tier))
    assert opts["format"] == "bv*+ba/b"
    assert opts["format_sort"] == [res, "vcodec:h264", "acodec:aac", "ext:mp4:m4a"]
    # The merge reassembles the separate streams the selector asks for.
    assert opts["merge_output_format"] == "mp4"
    assert "postprocessors" not in opts


def test_res_comes_from_the_domain_tier_not_a_literal() -> None:
    for tier in VideoTier:
        sort = _opts(VideoSpec(tier))["format_sort"]
        assert isinstance(sort, list)
        if tier.short_side is None:
            assert not any(key.startswith("res") for key in sort)
        else:
            assert sort[0] == f"res:{tier.short_side}"


def test_best_has_no_resolution_preference() -> None:
    opts = _opts(VideoSpec(VideoTier.BEST))
    assert opts["format"] == "bv*+ba/b"
    assert opts["format_sort"] == ["vcodec:h264", "acodec:aac", "ext:mp4:m4a"]


def test_video_never_filters_by_height_any_more() -> None:
    # A height filter is what turned a vertical 1080x1920 Short into
    # 480x854 (Stage 0). Quality is a sort now.
    for tier in VideoTier:
        assert "height" not in str(_opts(VideoSpec(tier))["format"])


def test_audio_opts_extract_mp3() -> None:
    opts = _opts(AudioSpec())
    # m4a first: a real audio-only track, rather than a full muxed stream
    # whose video half ffmpeg would just throw away.
    assert opts["format"] == "bestaudio[ext=m4a]/bestaudio/best"
    assert "format_sort" not in opts
    assert "merge_output_format" not in opts
    pp = opts["postprocessors"]
    assert isinstance(pp, list)
    assert pp[0]["key"] == "FFmpegExtractAudio"
    assert pp[0]["preferredcodec"] == "mp3"


def test_one_codec_constant_drives_both_sort_and_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quality buttons are computed from the preview's
    max_compatible_short_side; the download prefers the codec in
    format_sort. If they ever read two different constants, users get
    offered a 1080p the download won't pick. Flipping the ONE constant
    must move both."""
    formats = [
        {"vcodec": "h264", "width": 720, "height": 1280},
        {"vcodec": "h265", "width": 1080, "height": 1920},
    ]
    assert _max_compatible_short_side(formats) == 720
    assert "vcodec:h264" in _opts(VideoSpec(VideoTier.P720))["format_sort"]  # type: ignore[operator]

    monkeypatch.setattr(ytdlp_downloader, "_COMPATIBLE_VCODEC", "h265")

    assert _max_compatible_short_side(formats) == 1080
    sort = _opts(VideoSpec(VideoTier.P720))["format_sort"]
    assert "vcodec:h265" in sort  # type: ignore[operator]
    assert "vcodec:h264" not in sort  # type: ignore[operator]


def test_every_sort_codec_has_prefixes() -> None:
    # The preview side looks the constant up in this table.
    assert ytdlp_downloader._COMPATIBLE_VCODEC in ytdlp_downloader._VCODEC_PREFIXES


@pytest.mark.parametrize(
    ("formats", "expected"),
    [
        # avc1 spelling (YouTube), vertical: the SHORT side counts.
        ([{"vcodec": "avc1.640028", "width": 1080, "height": 1920}], 1080),
        # No compatible codec at all → fall back to every video format.
        ([{"vcodec": "vp09.00.40.08", "width": 1920, "height": 1080}], 1080),
        # Audio-only and storyboards are not video.
        ([{"vcodec": "none", "width": 1920, "height": 1080}], None),
        ([{"vcodec": "avc1", "width": None, "height": 1080}], None),
        ([], None),
    ],
)
def test_max_compatible_short_side(formats: list[dict[str, object]], expected: int | None) -> None:
    assert _max_compatible_short_side(formats) == expected  # type: ignore[arg-type]


def test_no_hardcoded_player_client_on_either_path() -> None:
    """Regression guard for Day 11C stage 1: pinning a youtube
    player_client is what limited every download to 360p."""
    for spec in _BOTH:
        assert "extractor_args" not in _opts(spec)


def test_shared_reliability_options_identical_across_formats() -> None:
    video, audio = (_opts(spec) for spec in _BOTH)
    for key in (
        "retries",
        "fragment_retries",
        "socket_timeout",
        "continuedl",
        "restrictfilenames",
        "noplaylist",
        "outtmpl",
        "post_hooks",
        "noprogress",
    ):
        assert video[key] == audio[key], f"shared option diverged: {key}"


def test_progress_bar_is_off_on_both_paths() -> None:
    # Progress goes through progress_hooks; without `noprogress` yt-dlp
    # still draws its bar on the worker's stdout despite `quiet`.
    for spec in _BOTH:
        assert _opts(spec)["noprogress"] is True


def test_max_filesize_backstop_applied_on_both_paths() -> None:
    # `res:` is only a preference, so the size guard must stay (bug #5).
    for spec in _BOTH:
        assert _opts(spec, 5_000_000)["max_filesize"] == 5_000_000


def test_no_max_filesize_key_when_unset() -> None:
    assert "max_filesize" not in _opts(VideoSpec(VideoTier.P720))
