"""PreviewDownloadUseCase — validate the URL, then ask DownloaderPort
for metadata. First use case that will eventually feed into
RequestDownloadUseCase (Day 5): preview → user confirms → real download.
"""

from __future__ import annotations

from src.domain.interfaces.downloader import DownloaderPort
from src.domain.value_objects.media_preview import MediaPreview
from src.domain.value_objects.url_validation import validate_url
from src.shared.logging import bind_log_context


class PreviewDownloadUseCase:
    def __init__(self, downloader: DownloaderPort) -> None:
        self._downloader = downloader

    async def execute(self, url: str) -> MediaPreview:
        validated_url = validate_url(url)
        preview = await self._downloader.get_preview(validated_url)
        # Errors later in the same update are then attributable to a
        # source (ADR 0006).
        bind_log_context(extractor_key=preview.extractor_key)
        return preview
