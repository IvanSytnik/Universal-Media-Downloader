"""DownloadSpec — WHAT the user asked to get out of a URL (Day 11C, v2).

Replaces the ``FormatKind`` + ``QualityKind`` pair on the request. That
pair could express nonsense (an mp3 "at 1080p") and forced every reader
to remember that audio rows carry a quality nobody reads. A sum type
makes the invalid combination unrepresentable: a ``VideoSpec`` has a
tier, an ``AudioSpec`` has a codec, and nothing has both.

``VideoTier`` is the SHORT side of the frame, not its height. A vertical
1080x1920 Short is "1080p" to a viewer; capping by height turned it into
480x854 (Day 11C stage 0 diagnostics). ``short_side`` is the ONE place
in the project that maps a tier to pixels — the downloader's format
sort and anything else that needs a number read it from here.

``BEST`` is the tier for sources where no choice is offered (TikTok,
Reels, X, or an unknown short side): take the best available, with no
resolution preference at all — hence ``short_side`` is None.

``FormatKind`` survives only as the persistence discriminator column;
``spec_kind``/``spec_video_tier`` derive the stored columns from a spec,
and ``spec_from_parts`` is the strict inverse. It raises ``ValueError``
on any combination a spec cannot express — there is no honest default
for "a video row with no tier" — and the caller that knows which row it
was (the repository) turns that into ``CorruptedRecordError``. The same
pair of primitives is what crosses the spawn boundary into the
downloader's child process.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from src.domain.value_objects.format_kind import FormatKind


class VideoTier(StrEnum):
    P720 = "p720"
    P1080 = "p1080"
    BEST = "best"

    @property
    def short_side(self) -> int | None:
        """Short-side pixel target for this tier — the single source of
        truth. None means "no preference" (take the best available)."""
        match self:
            case VideoTier.P720:
                return 720
            case VideoTier.P1080:
                return 1080
            case VideoTier.BEST:
                return None


class AudioCodec(StrEnum):
    MP3 = "mp3"


@dataclass(frozen=True, slots=True)
class VideoSpec:
    tier: VideoTier


@dataclass(frozen=True, slots=True)
class AudioSpec:
    codec: AudioCodec = AudioCodec.MP3


DownloadSpec = VideoSpec | AudioSpec

DEFAULT_DOWNLOAD_SPEC: Final[DownloadSpec] = VideoSpec(VideoTier.P720)


def spec_kind(spec: DownloadSpec) -> FormatKind:
    match spec:
        case VideoSpec():
            return FormatKind.VIDEO
        case AudioSpec():
            return FormatKind.AUDIO


def spec_video_tier(spec: DownloadSpec) -> VideoTier | None:
    match spec:
        case VideoSpec(tier=tier):
            return tier
        case AudioSpec():
            return None


def spec_from_parts(kind: str, video_tier: str | None) -> DownloadSpec:
    """Rebuild a spec from its stored/primitive form. Strict: raises
    ``ValueError`` for an unknown kind or tier and for a tier on the
    wrong kind (video without one, audio with one)."""
    match FormatKind(kind):
        case FormatKind.VIDEO:
            if video_tier is None:
                raise ValueError("video spec without a tier")
            return VideoSpec(VideoTier(video_tier))
        case FormatKind.AUDIO:
            if video_tier is not None:
                raise ValueError(f"audio spec with a video tier {video_tier!r}")
            return AudioSpec()
