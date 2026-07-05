"""URL validation — the first line of defense from SECURITY.md
("Validate every URL", "Never trust user input").

Deliberately minimal for Day 4: checks structure only (scheme + host),
not an allowlist of supported sites — yt-dlp itself is the source of
truth for "is this site supported" (it raises if not, and
YtDlpDownloader maps that to ExtractionError). A domain allowlist may
be added later (Phase 4, tied to abuse prevention / tariff limits),
but that's a product decision, not a Day 4 concern.
"""

from __future__ import annotations

from urllib.parse import urlparse

from src.domain.exceptions import UnsupportedURLError

_ALLOWED_SCHEMES = {"http", "https"}


def validate_url(raw_url: str) -> str:
    """Returns the trimmed URL if structurally valid, raises otherwise."""
    url = raw_url.strip()

    if not url:
        raise UnsupportedURLError("Пустая ссылка")

    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UnsupportedURLError(
            f"Неподдерживаемая схема ссылки: {parsed.scheme or '(отсутствует)'}"
        )

    if not parsed.netloc:
        raise UnsupportedURLError("Ссылка не содержит домен")

    return url


def validate_url_against_allowlist(raw_url: str, allowed_domains: frozenset[str]) -> str:
    """Structural validation + domain allowlist check (SECURITY.md:
    "allowlist поддерживаемых доменов, а не blacklist").

    Called at the Presentation boundary (handlers), NOT inside use cases —
    per PROJECT_SPEC §9 input validation happens at the edge, before data
    enters the Application layer. Use cases keep calling plain
    `validate_url` as a structural safety net.

    Matching is suffix-based per label: `youtube.com` allows
    `www.youtube.com` and `m.youtube.com`, but NOT `evilyoutube.com`
    (which a naive `endswith` would let through).

    An empty allowlist means "allow everything" — a deliberate escape
    hatch for local development, configured via Settings, never the
    production default.

    Raises:
        UnsupportedURLError: structurally invalid URL or domain not allowed.
    """
    url = validate_url(raw_url)

    if not allowed_domains:
        return url

    hostname = (urlparse(url).hostname or "").lower().rstrip(".")

    for domain in allowed_domains:
        d = domain.lower().lstrip(".")
        if hostname == d or hostname.endswith("." + d):
            return url

    raise UnsupportedURLError(
        "Этот сайт не поддерживается. Поддерживаемые: " + ", ".join(sorted(allowed_domains))
    )
