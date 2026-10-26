"""FormatPolicy — which formats a source may be downloaded as, and which
buttons the preview card should therefore offer (Day 11C v2).

Two jobs, one rule set, so the UI and the use case can never disagree:

* ``is_allowed`` is the ENFORCEMENT, called by RequestDownloadUseCase
  before anything is persisted. The buttons are only a hint — a stale
  card rendered before a kill-switch was flipped, or a forged callback,
  still lands here and is refused.
* ``offered_choices`` is the PRESENTATION hint: which of video / mp3 to
  show, and whether video needs a quality step.

The kill-switch is per extractor (lowercased yt-dlp ``extractor_key``)
and per format kind, from configuration: ``{"youtube": ["audio"]}``
hides and refuses mp3 for YouTube only.

Quality step thresholds work on the preview's
``max_compatible_short_side`` (short side of the best inline-playable
video, see MediaPreview):

* unknown, or <= 720 — no choice worth asking about: video goes straight
  to ``VideoSpec(BEST)``;
* 721..1079 — [720p, best] (best is the source's own top, e.g. 900p);
* >= 1080 — [720p, 1080p].

``default_video_spec`` is the spec a path WITHOUT buttons asks for
(``/download``): the same answer the card's video button would give —
``VideoSpec(BEST)`` when no quality step is offered, else 720p. It does
not check the kill-switch; ``is_allowed`` in the use case refuses a
disabled video exactly as it refuses a stale button.

No re-check in the worker (YAGNI): the policy is enforced once, at the
moment a request is created.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass

from src.domain.value_objects.download_spec import (
    DownloadSpec,
    VideoSpec,
    VideoTier,
    spec_kind,
)
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.media_preview import MediaPreview

# Thresholds are the tiers' own pixels (VideoTier.short_side stays the
# single tier→pixels mapping).
_QUALITY_STEP_ABOVE = VideoTier.P720.short_side or 0
_FULL_HD = VideoTier.P1080.short_side or 0

# The spec the video button downloads when there is no quality step.
DIRECT_VIDEO_SPEC: DownloadSpec = VideoSpec(VideoTier.BEST)


@dataclass(frozen=True, slots=True)
class OfferedChoices:
    """What the preview card offers. ``video_tiers`` empty means "no
    quality step": the video button downloads ``VideoSpec(BEST)``
    directly. Meaningless (and empty) when ``video`` is False."""

    video: bool
    audio: bool
    video_tiers: tuple[VideoTier, ...] = ()

    @property
    def has_quality_step(self) -> bool:
        return bool(self.video_tiers)


class FormatPolicy:
    def __init__(self, disabled_formats: Mapping[str, Collection[FormatKind]]) -> None:
        self._disabled = {key.lower(): frozenset(kinds) for key, kinds in disabled_formats.items()}

    def is_allowed(self, extractor_key: str, spec: DownloadSpec) -> bool:
        return spec_kind(spec) not in self._disabled.get(extractor_key.lower(), frozenset())

    def offered_choices(
        self, extractor_key: str, max_compatible_short_side: int | None
    ) -> OfferedChoices:
        disabled = self._disabled.get(extractor_key.lower(), frozenset())
        video = FormatKind.VIDEO not in disabled
        audio = FormatKind.AUDIO not in disabled
        if not video:
            return OfferedChoices(video=False, audio=audio)
        return OfferedChoices(
            video=True, audio=audio, video_tiers=_tiers_for(max_compatible_short_side)
        )

    def default_video_spec(self, preview: MediaPreview) -> DownloadSpec:
        tiers = _tiers_for(preview.max_compatible_short_side)
        return VideoSpec(VideoTier.P720) if tiers else DIRECT_VIDEO_SPEC


def _tiers_for(short_side: int | None) -> tuple[VideoTier, ...]:
    if short_side is None or short_side <= _QUALITY_STEP_ABOVE:
        return ()
    if short_side >= _FULL_HD:
        return (VideoTier.P720, VideoTier.P1080)
    return (VideoTier.P720, VideoTier.BEST)
