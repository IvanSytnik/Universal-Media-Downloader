"""Maps a raw yt-dlp error message to a domain extraction-error category.

This is deliberately an *Infrastructure* concern, not a Domain one: the
signatures below are yt-dlp's wording, which changes as yt-dlp evolves
and as sites change their responses. Keeping the string-matching here
means the domain vocabulary (the exception classes in
``src.domain.exceptions``) stays clean and library-agnostic, and the day
a signature changes we edit exactly one file.

Why match on message text at all, rather than on yt-dlp's own exception
subclasses (GeoRestrictedError, UnsupportedError, …)? Because in practice
``YoutubeDL.extract_info`` catches those internally and re-raises
everything as a single ``DownloadError`` carrying the original message as
text — so the subclass is gone by the time it reaches us, but the text
survives. Verified against yt-dlp directly (see tests). We therefore
classify on the one thing that reliably crosses the boundary: the string.

Matching rules:
- Case-insensitive substring checks against stable fragments, never the
  whole message (which includes volatile URLs, issue-tracker boilerplate,
  version hints).
- Order matters: more specific / higher-priority categories are checked
  first. The ``Unsupported URL`` split is checked late, because a bare
  "unsupported URL" is ambiguous (truly unsupported site vs. a supported
  site's photo endpoint) and we disambiguate using the URL shape.
- Anything unmatched falls through to the generic ``ExtractionError`` —
  never guess; a wrong specific message is worse than an honest generic
  one.
"""

from __future__ import annotations

from src.domain.exceptions import (
    AgeRestrictedError,
    ContentUnavailableError,
    ExtractionError,
    GeoRestrictedError,
    PrivateContentError,
    UnsupportedMediaError,
    UnsupportedURLError,
)

# Each entry: (list of lowercase substrings, exception type). First entry
# with ANY substring present wins — so ordering encodes priority.
_SIGNATURES: tuple[tuple[tuple[str, ...], type[ExtractionError]], ...] = (
    # Private / login-walled. Checked early: these often co-occur with
    # generic "unavailable" wording, and the access-specific message is
    # the more useful one for the user.
    (
        (
            "private",
            "login required",
            "log in",
            "sign in to view",
            "this post is not available",
            "requested content is not available",
            "you need to log in",
            "account is private",
            "only available to",
            "followers",
        ),
        PrivateContentError,
    ),
    # Age-gated. Before "unavailable" (an age wall sometimes also says
    # "not available") and before "sign in" alone (which private also
    # uses) — the age-specific phrasing is unambiguous.
    (
        (
            "sign in to confirm your age",
            "age-restricted",
            "age restricted",
            "inappropriate for some users",
            "confirm your age",
        ),
        AgeRestrictedError,
    ),
    # Geo-blocked.
    (
        (
            "geo",
            "not available in your country",
            "not available from your location",
            "blocked in your country",
            "available for the region",
            "video is restricted based on",
            "not made this video available in your country",
            "who has blocked it in your country",
            "not available in your location",
        ),
        GeoRestrictedError,
    ),
    # Removed / does not exist. Terminal — the item itself is gone.
    (
        (
            "video unavailable",
            "has been removed",
            "no longer available",
            "does not exist",
            "account has been terminated",
            "this video has been deleted",
            "content isn't available",
            "removed by the uploader",
            "page not found",
            "http error 404",
        ),
        ContentUnavailableError,
    ),
    # Supported site, unsupported media on it (photo/slideshow, no video
    # stream). The bare-"Unsupported URL" + photo-shape case is handled
    # separately in ``classify_error`` because it needs the URL, not just
    # the message.
    (
        (
            "no video formats found",
            "there's no video",
            "there is no video",
            "no media found",
            "unable to extract video",
        ),
        UnsupportedMediaError,
    ),
)

# Signals that a "Unsupported URL" is actually a photo/slideshow post on
# an otherwise-supported site, rather than a genuinely unsupported site.
_PHOTO_URL_MARKERS: tuple[str, ...] = ("/photo/", "/photos/", "/slideshow/")
_PHOTO_MSG_MARKERS: tuple[str, ...] = ("slideshow", "photo mode", "image post")


def classify_error(
    message: str, url: str
) -> type[ExtractionError] | type[UnsupportedURLError]:
    """Return the domain exception *type* best matching this yt-dlp error.

    ``url`` is used only to disambiguate a bare "Unsupported URL": a
    supported site's photo endpoint (e.g. a TikTok ``/photo/`` slideshow)
    is ``UnsupportedMediaError`` ("can't download photos yet"), while any
    other unsupported URL is ``UnsupportedURLError`` ("site not
    supported"). Everything else is decided from the message alone.

    The return type is a union: ``UnsupportedURLError`` isn't an
    ``ExtractionError`` subclass (it's a sibling under ``DownloaderError``
    for the "not a supported site at all" case), but both carry
    ``error_key`` and the caller re-raises whatever this returns, so the
    two are handled uniformly downstream.
    """
    lowered = message.lower()

    for fragments, exc_type in _SIGNATURES:
        if any(fragment in lowered for fragment in fragments):
            return exc_type

    if "unsupported url" in lowered:
        url_lowered = url.lower()
        if any(marker in url_lowered for marker in _PHOTO_URL_MARKERS) or any(
            marker in lowered for marker in _PHOTO_MSG_MARKERS
        ):
            return UnsupportedMediaError
        return UnsupportedURLError

    return ExtractionError
