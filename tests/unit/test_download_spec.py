"""Day 11C (v2): DownloadSpec and its stored form.

``spec_from_parts`` is the inverse of ``(spec_kind, spec_video_tier)``
and the only way a stored or pickled pair becomes a spec again, so the
round-trip is pinned for every spec shape, and every pair a spec cannot
express must raise — the repository relies on that to turn a bad row
into CorruptedRecordError instead of guessing.
"""

from __future__ import annotations

import pytest

from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
    spec_from_parts,
    spec_kind,
    spec_video_tier,
)
from src.domain.value_objects.format_kind import FormatKind

_ALL_SPECS: list[DownloadSpec] = [
    VideoSpec(VideoTier.P720),
    VideoSpec(VideoTier.P1080),
    VideoSpec(VideoTier.BEST),
    AudioSpec(),
]


@pytest.mark.parametrize(
    ("tier", "short_side"),
    [(VideoTier.P720, 720), (VideoTier.P1080, 1080), (VideoTier.BEST, None)],
)
def test_short_side(tier: VideoTier, short_side: int | None) -> None:
    assert tier.short_side == short_side


def test_every_tier_has_a_short_side_mapping() -> None:
    # A new member without a `case` would return None implicitly and
    # silently behave like BEST; only BEST may be None.
    assert [t for t in VideoTier if t.short_side is None] == [VideoTier.BEST]


def test_default_is_720p_video() -> None:
    assert VideoSpec(VideoTier.P720) == DEFAULT_DOWNLOAD_SPEC


@pytest.mark.parametrize(
    ("spec", "kind", "tier"),
    [
        (VideoSpec(VideoTier.P720), FormatKind.VIDEO, VideoTier.P720),
        (VideoSpec(VideoTier.P1080), FormatKind.VIDEO, VideoTier.P1080),
        (VideoSpec(VideoTier.BEST), FormatKind.VIDEO, VideoTier.BEST),
        (AudioSpec(), FormatKind.AUDIO, None),
    ],
)
def test_spec_to_parts(spec: DownloadSpec, kind: FormatKind, tier: VideoTier | None) -> None:
    assert spec_kind(spec) is kind
    assert spec_video_tier(spec) is tier


@pytest.mark.parametrize("spec", _ALL_SPECS)
def test_parts_roundtrip(spec: DownloadSpec) -> None:
    tier = spec_video_tier(spec)
    raw_tier = tier.value if tier is not None else None
    assert spec_from_parts(spec_kind(spec).value, raw_tier) == spec


@pytest.mark.parametrize(
    ("kind", "tier"),
    [
        ("video", None),
        ("audio", "p720"),
        ("audio", "best"),
        ("video", "p2160"),
        ("video", "hd_720"),  # a pre-0005 quality_kind value
        ("flac", None),
        ("", None),
    ],
)
def test_invalid_parts_raise(kind: str, tier: str | None) -> None:
    with pytest.raises(ValueError):
        spec_from_parts(kind, tier)


def test_specs_are_immutable_values() -> None:
    assert VideoSpec(VideoTier.P1080) == VideoSpec(VideoTier.P1080)
    assert hash(VideoSpec(VideoTier.P1080)) == hash(VideoSpec(VideoTier.P1080))
    with pytest.raises(AttributeError):
        VideoSpec(VideoTier.P720).tier = VideoTier.P1080  # type: ignore[misc]
