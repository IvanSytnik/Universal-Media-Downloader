"""DownloaderPort — domain interface for anything that can fetch media
metadata/content. No mention of yt-dlp here; PROJECT_SPEC §6.1 requires
the downloader to be completely independent from any specific extractor
implementation, not just from Telegram.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.media_preview import MediaPreview


class DownloaderPort(Protocol):
    async def get_preview(self, url: str) -> MediaPreview:
        """Fetch metadata for `url` without downloading any media.

        Raises:
            UnsupportedURLError: if the URL is malformed (should be rare —
                callers are expected to validate first, but implementations
                must not assume that happened).
            ExtractionError: if the underlying extractor fails (private/
                deleted video, unsupported site, network error, etc.).
        """
        ...

    async def download(self, url: str, options: DownloadOptions) -> Path:
        """Downloads the media at `url` into `options.output_dir`.

        Returns the path to the downloaded file. Implementations must
        enforce `options.timeout_seconds` with a real cancellation
        guarantee (not just "give up waiting") — see PROJECT_SPEC §6.4
        and YtDlpDownloader's module docstring for why.

        Raises:
            UnsupportedURLError: malformed URL.
            ExtractionError: download failed, timed out, or exceeded
                `options.max_filesize_bytes`.
        """
        ...
