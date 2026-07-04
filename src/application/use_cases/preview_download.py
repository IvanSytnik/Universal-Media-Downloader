"""PreviewDownloadUseCase — validate the URL, then ask DownloaderPort
for metadata. First use case that will eventually feed into
RequestDownloadUseCase (Day 5): preview → user confirms → real download.
"""

from __future__ import annotations

from src.domain.interfaces.downloader import DownloaderPort
from src.domain.value_objects.media_preview import MediaPreview
from src.domain.value_objects.url_validation import validate_url


class PreviewDownloadUseCase:
    def __init__(self, downloader: DownloaderPort) -> None:
        self._downloader = downloader

    async def execute(self, url: str) -> MediaPreview:
        validated_url = validate_url(url)
        return await self._downloader.get_preview(validated_url)
