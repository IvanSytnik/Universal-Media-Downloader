"""PreviewContext — what a preview card's buttons are allowed to act on.

Day 7 stored only the URL under the card's token. Day 11C (v2) needs two
more facts at button time — which extractor the URL belongs to (for the
FormatPolicy kill-switch) and the best compatible short side (for which
quality buttons to show) — and they must come from the PREVIEW, never
from callback data: a callback is client-supplied and can be forged or
stale, the stored context is what the server itself observed.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.value_objects.media_preview import MediaPreview


@dataclass(frozen=True, slots=True)
class PreviewContext:
    url: str
    extractor_key: str
    max_compatible_short_side: int | None

    @classmethod
    def from_preview(cls, preview: MediaPreview) -> PreviewContext:
        return cls(
            url=preview.source_url,
            extractor_key=preview.extractor_key,
            max_compatible_short_side=preview.max_compatible_short_side,
        )
