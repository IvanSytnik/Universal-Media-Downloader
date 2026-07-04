"""MediaPreview — metadata about a piece of media, fetched WITHOUT
downloading it. This is the result of the two-phase download flow
decided in PROJECT_SPEC §6.4: preview first, actual download later
(Day 5), only after the user confirms and tariff limits are checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.value_objects.enums import MediaType


@dataclass(frozen=True, slots=True)
class MediaPreview:
    source_url: str
    title: str
    duration_seconds: int | None
    uploader: str | None
    thumbnail_url: str | None
    media_type: MediaType
