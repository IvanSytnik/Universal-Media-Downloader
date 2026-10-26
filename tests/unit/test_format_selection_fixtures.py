"""What the download actually SELECTS, on real format lists (Day 11C v2).

``test_download_ydl_opts.py`` pins the option strings; this pins their
meaning. The fixtures are Stage 0 captures (``extract_info`` trimmed to
the format fields that drive yt-dlp's sorting — including ``language``:
without it a dubbed audio track wins, see test_original_audio_track_*)
and each case runs yt-dlp's OWN selector over them with the PRODUCTION
ydl_opts — no network, no reimplementation of the selection logic.

It also closes the loop from preview to buttons: the preview's
``max_compatible_short_side`` computed from the same fixture, fed to the
real FormatPolicy, must offer exactly the expected quality step.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yt_dlp

from src.application.policies.format_policy import FormatPolicy
from src.domain.value_objects.download_spec import (
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)
from src.infrastructure.downloader.ytdlp_downloader import (
    _build_download_ydl_opts,
    _max_compatible_short_side,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ytdlp_formats"


def _fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_FIXTURES / f"{name}.json").read_text())
    return data


def _select(name: str, spec: DownloadSpec) -> list[dict[str, Any]]:
    """Run yt-dlp's selector with the production opts; return the chosen
    format(s) — [video, audio] for a merge, [single] otherwise."""
    info = copy.deepcopy(_fixture(name))
    for f in info["formats"]:
        f.setdefault("url", "https://example.invalid/media")
        f.setdefault("protocol", "https")
    info.update(
        id="fixture",
        title="fixture",
        webpage_url="https://example.invalid/",
        extractor=info["extractor_key"].lower(),
    )

    def _hook(_: str) -> None:  # pragma: no cover - nothing is downloaded
        pass

    opts = _build_download_ydl_opts("/tmp/fixture", None, spec, _hook)
    opts.update(simulate=True, quiet=True, no_warnings=True)
    opts.pop("postprocessors", None)  # selection only — nothing to transcode
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.process_ie_result(info, download=False)
    chosen: list[dict[str, Any]] = result.get("requested_formats") or [result]
    return chosen


def _video(chosen: list[dict[str, Any]]) -> dict[str, Any]:
    return next(f for f in chosen if f.get("vcodec") not in (None, "none"))


def _audio(chosen: list[dict[str, Any]]) -> dict[str, Any]:
    return next(f for f in chosen if f.get("acodec") not in (None, "none"))


def _short_side(fmt: dict[str, Any]) -> int:
    return min(int(fmt["width"]), int(fmt["height"]))


# --- video tiers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "spec", "short_side"),
    [
        # The Stage 0 regression: a vertical 1080x1920 Short. The old
        # height cap gave 360x640 at "720" and 480x854 at "1080".
        ("youtube_shorts", VideoSpec(VideoTier.P720), 720),
        ("youtube_shorts", VideoSpec(VideoTier.P1080), 1080),
        ("youtube_shorts", VideoSpec(VideoTier.BEST), 1080),
        ("youtube_1080", VideoSpec(VideoTier.P720), 720),
        ("youtube_1080", VideoSpec(VideoTier.P1080), 1080),
        ("youtube_1080", VideoSpec(VideoTier.BEST), 1080),
        # TikTok: 1080 exists only as video-only h265; the inline-playable
        # h264 top is 720, which BEST prefers.
        ("tiktok", VideoSpec(VideoTier.BEST), 720),
    ],
)
def test_tier_selects_the_expected_short_side(
    name: str, spec: DownloadSpec, short_side: int
) -> None:
    video = _video(_select(name, spec))
    assert _short_side(video) == short_side


@pytest.mark.parametrize(
    ("name", "tier"),
    [
        (name, tier)
        for name in ("youtube_shorts", "youtube_1080", "tiktok")
        for tier in VideoTier
        # TikTok P1080 is h265-only and never offered for this source
        # (see test_offered_choices_from_fixture).
        if not (name == "tiktok" and tier is VideoTier.P1080)
    ],
)
def test_video_is_always_the_inline_playable_codec(name: str, tier: VideoTier) -> None:
    # Where the compatible tier exists, h264/avc1 wins over vp9/av1/h265 —
    # that is what keeps the file playing inline in Telegram.
    vcodec = str(_video(_select(name, VideoSpec(tier)))["vcodec"])
    assert vcodec.startswith(("avc1", "h264"))


def test_youtube_1080_merges_mp4_video_with_m4a_audio() -> None:
    chosen = _select("youtube_1080", VideoSpec(VideoTier.P1080))
    assert len(chosen) == 2
    assert _video(chosen)["ext"] == "mp4"
    assert _audio(chosen)["ext"] == "m4a"


# --- audio: the original track, never an auto-dub ---------------------------------


@pytest.mark.parametrize(
    "spec",
    [VideoSpec(VideoTier.P720), VideoSpec(VideoTier.P1080), AudioSpec()],
)
def test_original_audio_track_is_selected_not_a_dub(spec: DownloadSpec) -> None:
    """youtube_1080 carries 20 auto-dubbed tracks next to the original.
    Stage 0 found that a fixture without `language` picks 140-9 (a dub);
    with it, yt-dlp's own ranking picks the original 140-20 (en-US). The
    same must hold on the mp3 path, whose selector is different."""
    audio = _audio(_select("youtube_1080", spec))
    assert audio["format_id"] == "140-20"
    assert audio["language"] == "en-US"


# --- preview → buttons ------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "short_side", "tiers"),
    [
        ("youtube_shorts", 1080, (VideoTier.P720, VideoTier.P1080)),
        ("youtube_1080", 1080, (VideoTier.P720, VideoTier.P1080)),
        ("tiktok", 720, ()),  # no quality step → straight to vbest
    ],
)
def test_offered_choices_from_fixture(
    name: str, short_side: int, tiers: tuple[VideoTier, ...]
) -> None:
    fixture = _fixture(name)
    computed = _max_compatible_short_side(fixture["formats"])
    assert computed == short_side

    choices = FormatPolicy({}).offered_choices(fixture["extractor_key"].lower(), computed)
    assert choices.video and choices.audio
    assert choices.video_tiers == tiers
