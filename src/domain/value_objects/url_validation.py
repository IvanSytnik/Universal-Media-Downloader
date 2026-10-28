"""URL validation — the first line of defense against untrusted input
("validate every URL", "never trust user input"; see SECURITY.md).

Deliberately minimal for Day 4: checks structure only (scheme + host),
not an allowlist of supported sites — yt-dlp itself is the source of
truth for "is this site supported" (it raises if not, and
YtDlpDownloader maps that to ExtractionError). A domain allowlist may
be added later (Phase 4, tied to abuse prevention / tariff limits),
but that's a product decision, not a Day 4 concern.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.domain.exceptions import (
    DomainBlockedError,
    DomainNotAllowedError,
    EmptyURLError,
    MissingURLHostError,
    UnsupportedURLSchemeError,
)

_ALLOWED_SCHEMES = {"http", "https"}


def validate_url(raw_url: str) -> str:
    """Returns the trimmed URL if structurally valid, raises otherwise."""
    url = raw_url.strip()

    if not url:
        raise EmptyURLError

    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsupportedURLSchemeError

    if not parsed.netloc:
        raise MissingURLHostError

    return url


def validate_url_against_allowlist(
    raw_url: str,
    allowed_domains: frozenset[str],
    blocked_domains: frozenset[str] = frozenset(),
) -> str:
    """Structural validation + domain allowlist check (SECURITY.md: an
    allowlist of supported domains, not a blocklist).

    Called at the Presentation boundary (handlers), NOT inside use cases —
    per SECURITY.md input validation happens at the edge, before data
    enters the Application layer. Use cases keep calling plain
    `validate_url` as a structural safety net.

    Matching is suffix-based per label: `youtube.com` allows
    `www.youtube.com` and `m.youtube.com`, but NOT `evilyoutube.com`
    (which a naive `endswith` would let through).

    An empty allowlist means "allow everything" — a deliberate escape
    hatch for local development, configured via Settings, never the
    production default.

    ``blocked_domains`` carves exceptions out of the allowlist, with the
    same suffix matching, and wins over it (also over an empty
    allowlist). It exists for subdomains the allowlist admits by suffix
    but that nothing downstream can tell apart: ``music.youtube.com``
    resolves to the same yt-dlp extractor as YouTube, so the per-extractor
    FormatPolicy cannot exclude it — only the URL can. A blocked site is
    refused as "not supported", without the list of supported sites.

    Raises:
        UnsupportedURLError: a subclass per reason — EmptyURLError,
            UnsupportedURLSchemeError, MissingURLHostError,
            DomainBlockedError, DomainNotAllowedError.
    """
    url = validate_url(raw_url)
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")

    if any(_host_matches(hostname, domain) for domain in blocked_domains):
        raise DomainBlockedError
    if not allowed_domains or any(_host_matches(hostname, d) for d in allowed_domains):
        return url

    raise DomainNotAllowedError(tuple(sorted(allowed_domains)))


def _host_matches(hostname: str, domain: str) -> bool:
    d = domain.lower().lstrip(".")
    return hostname == d or hostname.endswith("." + d)
