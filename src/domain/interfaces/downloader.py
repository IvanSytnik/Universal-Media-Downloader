"""DownloaderPort — domain interface for anything that can fetch media
metadata/content. No mention of yt-dlp here; PROJECT_SPEC §6.1 requires
the downloader to be completely independent from any specific extractor
implementation, not just from Telegram.

Day 11B adds an optional ``progress_callback`` to ``download()``: an
async hook the implementation invokes zero or more times while the
download is in flight, each time with a fresh ``DownloadProgress``
snapshot. It's optional (defaults to None) so every existing caller
keeps working unchanged — progress reporting is strictly opt-in, same
posture as ``format_kind`` in Day 11A.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol

from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.media_preview import MediaPreview

ProgressCallback = Callable[[DownloadProgress], Awaitable[None]]


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

    async def download(
        self,
        url: str,
        options: DownloadOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> Path:
        """Downloads the media at `url` into `options.output_dir`.

        Returns the path to the downloaded file. Implementations must
        enforce `options.timeout_seconds` with a real cancellation
        guarantee (not just "give up waiting") — see PROJECT_SPEC §6.4
        and YtDlpDownloader's module docstring for why.

        ``progress_callback``, when given, is awaited with a
        ``DownloadProgress`` snapshot periodically during the download
        phase (not during postprocessing/transcode — out of scope for
        Day 11B). Implementations must never let a failing callback abort
        the download itself.

        Raises:
            UnsupportedURLError: malformed URL.
            ExtractionError: download failed, timed out, or exceeded
                `options.max_filesize_bytes`.
        """
        ...
