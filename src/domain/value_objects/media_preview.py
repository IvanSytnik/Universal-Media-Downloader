"""MediaPreview — metadata about a piece of media, fetched WITHOUT
downloading it. This is the result of the two-phase download flow
(docs/architecture.md, Two-phase flow): preview first, actual download later
(Day 5), only after the user confirms and tariff limits are checked.

Day 11C (v2) adds two facts the format choice is decided from, both
computed by the downloader from the extractor's own format list:

* ``extractor_key`` — lowercased canonical extractor id ("youtube",
  "tiktok", ...), the key FormatPolicy's per-source kill-switch uses.
* ``max_compatible_short_side`` — the largest short side among video
  formats in the codec Telegram plays inline (falling back to all video
  formats when the source has none of it); None when unknown. Short
  side, not height: a vertical 1080x1920 video is "1080p".

Both are required, with no defaults, on purpose: a preview built without
them would silently offer the wrong buttons (lesson 11A.1).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.value_objects.enums import MediaType


@dataclass(frozen=True, slots=True)
class MediaPreview:
    source_url: str
    title: str | None
    duration_seconds: int | None
    uploader: str | None
    thumbnail_url: str | None
    media_type: MediaType
    extractor_key: str
    max_compatible_short_side: int | None
