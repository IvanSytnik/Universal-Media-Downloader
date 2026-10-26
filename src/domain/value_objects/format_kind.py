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

Day 11C (v2): the request now carries a ``DownloadSpec`` (see
download_spec.py); this enum remains as the persisted discriminator
column and is derived from the spec with ``spec_kind``. It no longer has
a lenient ``from_db_value``: a stored kind is only meaningful together
with its ``video_tier`` column, and ``spec_from_parts`` parses the pair
strictly.
"""

from __future__ import annotations

from enum import StrEnum


class FormatKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
