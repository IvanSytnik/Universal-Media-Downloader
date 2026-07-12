"""Domain-level exceptions for the downloader.

Infrastructure adapters (e.g. YtDlpDownloader) must catch library-specific
exceptions (yt_dlp.utils.DownloadError, etc.) and re-raise as these —
the domain and application layers must never see yt-dlp's exception
types directly. That's what keeps PreviewDownloadUseCase testable with
a fake and swappable to a different extractor later without touching
application code.

Day 10 — extraction failures are now *categorized*. Before Day 10 every
yt-dlp failure surfaced to the user as one generic "couldn't fetch info"
message, which is wrong UX for cases the user could act on (a private
account, a geo-blocked video) or that we simply don't support yet (a
TikTok photo/slideshow post — the real case that triggered this work).

The categories are modelled as subclasses of ``ExtractionError`` on
purpose, for backward compatibility: existing ``except ExtractionError``
handlers keep catching every one of them. What each category adds is a
stable ``error_key`` — a *semantic* identifier (NOT localized text; the
domain knows nothing about languages), which the Presentation layer maps
to an FTL message key, and which the worker path resolves to a localized
string via ErrorLocalizerPort. Classification itself (yt-dlp message →
which subclass) is an Infrastructure concern and lives in the adapter,
not here — the domain only defines the vocabulary.
"""

from __future__ import annotations


class DownloaderError(Exception):
    """Base class for all downloader-related errors."""


class UnsupportedURLError(DownloaderError):
    """The given URL is malformed or not from a supported source.

    Distinct from ``UnsupportedMediaError``: this means "we don't handle
    this site / this isn't a valid link at all", raised by our own
    allowlist validation *before* yt-dlp runs, or when yt-dlp reports a
    genuinely unsupported URL with no sign it's a known site's
    unsupported media type. ``error_key`` lets the Presentation layer
    treat it uniformly with the categorized extraction errors below.
    """

    error_key = "error-unsupported-site"


class ExtractionError(DownloaderError):
    """yt-dlp (or whatever extractor is behind DownloaderPort) failed to
    retrieve information for an otherwise well-formed URL.

    Also the fallback category: any failure the adapter's classifier
    can't confidently place into a more specific subclass surfaces as a
    plain ``ExtractionError`` with the generic ``error_key``. Never put
    the raw yt-dlp message into the text shown to the user — it's
    diagnostic (see the adapter and bug #6 in HANDOFF); log it, show the
    keyed message.
    """

    error_key = "error-extraction-failed"


class PrivateContentError(ExtractionError):
    """The content requires authentication we don't have: a private
    account, a login wall, a followers-only post. The user needs to know
    it's an access problem, not a transient failure to retry."""

    error_key = "error-private"


class GeoRestrictedError(ExtractionError):
    """The content is blocked in the region our server requests from.
    Nothing the user can do from their side, and retrying won't help —
    so the message says so rather than inviting a pointless retry."""

    error_key = "error-geo"


class AgeRestrictedError(ExtractionError):
    """The content is age-gated and requires a signed-in, age-verified
    session we don't provide. Distinct from private: the account isn't
    private, the specific item is gated."""

    error_key = "error-age"


class ContentUnavailableError(ExtractionError):
    """The content no longer exists or was removed: deleted video,
    terminated account, "video unavailable". Terminal — the link itself
    is dead, not our access to it."""

    error_key = "error-unavailable"


class UnsupportedMediaError(ExtractionError):
    """The site IS supported, but this particular post isn't something we
    can download yet — the concrete case being a TikTok photo/slideshow
    post (no video stream). Kept separate from ``UnsupportedURLError`` so
    we don't lie ("site not supported") about a site we do support; the
    honest message is "this post is a photo/slideshow, which I can't
    download yet". Full photo/carousel support is a separate day (it
    extends MediaType and the delivery logic)."""

    error_key = "error-unsupported-media"


class DownloadTimeoutError(ExtractionError):
    """The download started but exceeded the time limit and was aborted.
    Distinct from a plain extraction failure — the item was reachable,
    it just took too long — so the message says "took too long, try
    again" rather than "couldn't fetch info"."""

    error_key = "error-timeout"


class FileTooLargeError(ExtractionError):
    """The media exceeds the deliverable size limit. Unlike the other
    categories, this carries data (the estimated size and the limit, in
    MB) so the message can state both — the Presentation/worker layers
    pass these as Fluent arguments. The limit is real and actionable
    information, not diagnostics, so surfacing it is correct (contrast
    bug #6, which is about not leaking *internal* diagnostics)."""

    error_key = "error-too-large"

    def __init__(self, estimated_mb: int, limit_mb: int) -> None:
        super().__init__()
        self.estimated_mb = estimated_mb
        self.limit_mb = limit_mb


class NotifierError(Exception):
    """Delivering a result to the user failed (file too large, user
    blocked the bot, Telegram API error, etc.)."""
