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

from uuid import UUID


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


class PreviewTimeoutError(ExtractionError):
    """Fetching the preview exceeded its overall time limit and the
    extraction was killed. Its own key, not ``error-timeout``: nothing
    was being downloaded yet, so "the download took too long" would be
    wrong — the user should just try again a bit later."""

    error_key = "error-preview-timeout"


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


class FormatNotAllowedError(DownloaderError):
    """The requested format is switched off for this source by
    FormatPolicy (Day 11C, per-extractor kill-switch).

    Raised by RequestDownloadUseCase BEFORE anything is persisted, so a
    stale button rendered before the switch was flipped — or a forged
    callback — never becomes a request. Not an ``ExtractionError``:
    nothing was extracted, the request was refused. It sits under
    ``DownloaderError`` only because the domain has no common base for
    "error with an ``error_key``" (``CorruptedRecordError`` hangs off
    ``Exception`` directly) and ``format_download_error`` — the single
    presentation-side localizer — is typed on ``DownloaderError``. A
    shared keyed-error base would be the cleaner home; introducing it is
    a separate refactor across both hierarchies.
    """

    error_key = "error-format-not-allowed"


class StaleRequestError(DownloaderError):
    """A request sat in pending/processing past any live job's lifetime
    (worker crash, arq cancelling at ``job_timeout``, a lost queue
    message) and the reaper failed it.

    Never raised: the reaper finds these rows, nothing throws. It is a
    class for the same reason ``FormatNotAllowedError`` is one — the
    domain's error keys live on its error types, and this is where a
    reader looks for them.
    """

    error_key = "error-request-stale"


class NotifierError(Exception):
    """Delivering a result to the user failed (file too large, user
    blocked the bot, Telegram API error, etc.)."""


class CorruptedRecordError(Exception):
    """A persisted row holds a value this build cannot interpret, and no
    honest fallback exists for it.

    Raised only for columns where degrading would LIE. ``media_type``
    has a truthful default ("unknown"), so an unrecognized value there
    degrades with a warning. ``status`` has none: silently reading a
    corrupt status as "pending" would resurrect a finished request and
    re-run a download the user already received. Neither does the
    ``(format_kind, video_tier)`` pair that encodes the DownloadSpec
    (Day 11C v2): guessing a format the user did not pick is exactly the
    silent wrong delivery this error exists to prevent. For that pair
    ``column`` is ``"spec"`` and ``raw_value`` is ``"<kind>/<tier>"``.

    It deliberately does NOT raise a bare ``ValueError`` at the call
    site (which is what ``DownloadStatus(row.status)`` used to do). That
    would escape the worker unhandled, arq would log a traceback, and
    the user — whose request was already accepted — would get nothing at
    all. Instead this carries an ``error_key`` like every downloader
    error, so the worker path marks the request failed and delivers one
    short localized message, with the diagnostics going to the log
    (bugs #6 and #13).

    ``request_id``/``user_id`` come from the same row: they are uuid
    columns, so they are readable even when an enum column next to them
    is not — which is what makes notifying the user possible at all from
    inside a failed read.
    """

    error_key = "error-internal"

    def __init__(
        self,
        *,
        column: str,
        raw_value: str,
        request_id: UUID,
        user_id: UUID,
    ) -> None:
        super().__init__(f"unreadable value in column {column!r}")
        self.column = column
        self.raw_value = raw_value
        self.request_id = request_id
        self.user_id = user_id
