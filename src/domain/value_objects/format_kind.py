"""FormatKind — what the user wants out of a download: the full video,
or just the audio track extracted to a standalone file (Day 11A).

Kept as its own value object (not folded into MediaType) on purpose:
``MediaType`` describes what the *source* IS (the preview says "this is a
video" / "this is audio"), whereas ``FormatKind`` describes what the user
ASKED FOR. A single source video can be downloaded as VIDEO or as AUDIO
(mp3) — those are two different intents against the same media, so they
are two different concepts. Collapsing them would make "video source,
audio download" inexpressible.

Domain-only: no yt-dlp format strings here. The mapping from this intent
to concrete ``ydl_opts`` (format selector, FFmpegExtractAudio
postprocessor) lives in the infrastructure downloader, where extractor
specifics belong.
"""

from __future__ import annotations

from enum import StrEnum


class FormatKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"

    @classmethod
    def from_db_value(cls, value: str) -> FormatKind:
        """Parse a stored value, degrading to VIDEO instead of raising.

        VIDEO is the pre-Day-11A behaviour and the column's
        server_default, so an unreadable value falls back to what the
        row would have meant before this field existed. Delivering a
        video where mp3 was asked for is a visible, recoverable mistake
        (the user retries); a ``ValueError`` inside the worker is an
        invisible one — the user gets nothing.
        """
        try:
            return cls(value)
        except ValueError:
            return cls.VIDEO
