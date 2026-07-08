"""Shared Presentation-layer formatting helpers.

Day 9: every user-visible string now comes from Fluent via an
``I18nContext`` (``i18n``), never from a hardcoded literal. These helpers
stay in the Presentation layer — they format *domain* objects
(MediaPreview) into *localized* text, which is exactly a Presentation
concern. The data-driven shape of ``format_help`` (platforms from the
allowlist, limits from Settings — DRY, docs can't drift from behaviour)
is preserved: those values are now passed as Fluent arguments instead of
being f-string-interpolated.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram_i18n import I18nContext

from src.config.settings import Settings
from src.domain.value_objects.media_preview import MediaPreview


def format_help(i18n: I18nContext, settings: Settings) -> str:
    """Help text for /help and the ℹ️ button (single source — DRY).

    Still built from Settings, not hardcoded lists: the platform list is
    the actual allowlist, the limits are the actual rate-limit values.
    Day 9 moved the *wrapper text* into FTL (``help-text``) while keeping
    the data-driven values as arguments — structure localized, behaviour
    unchanged.
    """
    platforms = ", ".join(sorted(settings.allowed_domains))
    if not platforms:
        # Dev escape hatch (empty allowlist). Localized fallback label
        # rather than an empty platform line.
        platforms = i18n.get("help-any-site")
    return i18n.get(
        "help-text",
        platforms=html_escape(platforms),
        downloads=settings.rate_limit_downloads_per_hour,
        previews=settings.rate_limit_previews_per_minute,
        filesize=settings.max_deliverable_file_size_mb,
    )


def format_duration(i18n: I18nContext, seconds: int | None) -> str:
    if seconds is None:
        return i18n.get("preview-duration-unknown")
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_preview(i18n: I18nContext, preview: MediaPreview) -> str:
    # `title` and `uploader` come from the source site via yt-dlp —
    # untrusted external data. The bot's default parse_mode is HTML, so we
    # html-escape BEFORE handing the values to Fluent (Fluent itself does
    # no HTML escaping). Same reasoning as before Day 9.
    title = html_escape(preview.title)
    uploader = (
        html_escape(preview.uploader)
        if preview.uploader
        else i18n.get("preview-uploader-unknown")
    )
    return i18n.get(
        "preview-card",
        title=title,
        uploader=uploader,
        duration=format_duration(i18n, preview.duration_seconds),
        mediatype=preview.media_type.value,
    )


def format_retry_after(i18n: I18nContext, seconds: int) -> str:
    """Human-friendly rate-limit message. Minutes are rounded up so we
    never promise a shorter wait than reality. Pluralization (ru needs
    one/few/many) is handled by Fluent selectors in the FTL, not here."""
    if seconds < 60:
        return i18n.get("rate-limit-seconds", seconds=seconds)
    minutes = -(-seconds // 60)  # ceil
    return i18n.get("rate-limit-minutes", minutes=minutes)
