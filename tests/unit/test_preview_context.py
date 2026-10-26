"""PreviewContext is built from the preview and nothing else (Day 11C v2):
the buttons later act on these fields, so each must be copied from what
the extractor observed."""

from __future__ import annotations

from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview
from src.domain.value_objects.preview_context import PreviewContext


def test_from_preview_copies_the_observed_fields() -> None:
    preview = MediaPreview(
        source_url="https://www.tiktok.com/@nasa/video/1",
        title="t",
        duration_seconds=None,
        uploader=None,
        thumbnail_url=None,
        media_type=MediaType.VIDEO,
        extractor_key="tiktok",
        max_compatible_short_side=720,
    )
    assert PreviewContext.from_preview(preview) == PreviewContext(
        url="https://www.tiktok.com/@nasa/video/1",
        extractor_key="tiktok",
        max_compatible_short_side=720,
    )
