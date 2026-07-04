"""Domain-level exceptions for the downloader.

Infrastructure adapters (e.g. YtDlpDownloader) must catch library-specific
exceptions (yt_dlp.utils.DownloadError, etc.) and re-raise as these —
the domain and application layers must never see yt-dlp's exception
types directly. That's what keeps PreviewDownloadUseCase testable with
a fake and swappable to a different extractor later without touching
application code.
"""

from __future__ import annotations


class DownloaderError(Exception):
    """Base class for all downloader-related errors."""


class UnsupportedURLError(DownloaderError):
    """The given URL is malformed or not from a supported source."""


class ExtractionError(DownloaderError):
    """yt-dlp (or whatever extractor is behind DownloaderPort) failed
    to retrieve information for an otherwise well-formed URL."""


class NotifierError(Exception):
    """Delivering a result to the user failed (file too large, user
    blocked the bot, Telegram API error, etc.)."""
