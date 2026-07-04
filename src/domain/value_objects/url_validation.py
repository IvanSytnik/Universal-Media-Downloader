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
