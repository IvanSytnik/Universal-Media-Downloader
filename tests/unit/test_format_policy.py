"""FormatPolicy (Day 11C v2): the per-source kill-switch and the quality
step thresholds. Enforcement (``is_allowed``) and presentation
(``offered_choices``) read ONE rule set, so these tests check both sides
of each rule."""

from __future__ import annotations

import pytest

from src.application.policies.format_policy import (
    DIRECT_VIDEO_SPEC,
    FormatPolicy,
    OfferedChoices,
)
from src.domain.value_objects.download_spec import AudioSpec, VideoSpec, VideoTier
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.media_preview import MediaPreview

_OPEN = FormatPolicy({})
_NO_YT_AUDIO = FormatPolicy({"YouTube": [FormatKind.AUDIO]})


# --- kill-switch ----------------------------------------------------------------


def test_everything_allowed_by_default() -> None:
    for spec in (AudioSpec(), *(VideoSpec(t) for t in VideoTier)):
        assert _OPEN.is_allowed("youtube", spec)


@pytest.mark.parametrize("key", ["youtube", "YOUTUBE", "YouTube"])
def test_disabled_audio_for_youtube_is_refused_and_hidden(key: str) -> None:
    # Config keys and extractor keys are both case-normalized.
    assert not _NO_YT_AUDIO.is_allowed(key, AudioSpec())
    choices = _NO_YT_AUDIO.offered_choices(key, 1080)
    assert choices.audio is False
    assert choices.video is True


def test_kill_switch_is_scoped_to_one_extractor_and_one_kind() -> None:
    assert _NO_YT_AUDIO.is_allowed("youtube", VideoSpec(VideoTier.P1080))
    assert _NO_YT_AUDIO.is_allowed("tiktok", AudioSpec())
    assert _NO_YT_AUDIO.offered_choices("tiktok", None).audio is True


def test_disabled_video_hides_video_and_the_quality_step() -> None:
    policy = FormatPolicy({"youtube": [FormatKind.VIDEO]})
    assert not policy.is_allowed("youtube", VideoSpec(VideoTier.BEST))
    assert policy.offered_choices("youtube", 1080) == OfferedChoices(video=False, audio=True)


# --- quality step thresholds ----------------------------------------------------


@pytest.mark.parametrize(
    ("short_side", "tiers"),
    [
        (None, ()),  # unknown → straight to BEST
        (360, ()),
        (720, ()),  # nothing above 720 to choose
        (721, (VideoTier.P720, VideoTier.BEST)),
        (900, (VideoTier.P720, VideoTier.BEST)),
        (1079, (VideoTier.P720, VideoTier.BEST)),
        (1080, (VideoTier.P720, VideoTier.P1080)),
        (2160, (VideoTier.P720, VideoTier.P1080)),
    ],
)
def test_quality_step_thresholds(short_side: int | None, tiers: tuple[VideoTier, ...]) -> None:
    choices = _OPEN.offered_choices("youtube", short_side)
    assert choices.video_tiers == tiers
    assert choices.has_quality_step is bool(tiers)


def test_no_quality_step_means_video_downloads_best() -> None:
    assert VideoSpec(VideoTier.BEST) == DIRECT_VIDEO_SPEC


# --- default_video_spec: the spec a path without buttons asks for ---------------


def _preview(short_side: int | None) -> MediaPreview:
    return MediaPreview(
        source_url="https://example.com/v",
        title="t",
        duration_seconds=None,
        thumbnail_url=None,
        uploader=None,
        media_type=MediaType.VIDEO,
        extractor_key="youtube",
        max_compatible_short_side=short_side,
    )


@pytest.mark.parametrize(
    ("short_side", "expected"),
    [
        # No quality step offered → what the card's video button downloads.
        (None, DIRECT_VIDEO_SPEC),
        (720, DIRECT_VIDEO_SPEC),
        # A quality step exists → its first tier, 720p.
        (900, VideoSpec(VideoTier.P720)),
        (1080, VideoSpec(VideoTier.P720)),
    ],
)
def test_default_video_spec_matches_the_video_button(
    short_side: int | None, expected: VideoSpec
) -> None:
    assert _OPEN.default_video_spec(_preview(short_side)) == expected


def test_default_video_spec_is_still_refused_when_video_is_disabled() -> None:
    # It does not check the kill-switch itself; the use case does, via
    # is_allowed — the same gate a button goes through.
    no_video = FormatPolicy({"youtube": [FormatKind.VIDEO]})
    spec = no_video.default_video_spec(_preview(1080))
    assert not no_video.is_allowed("youtube", spec)
