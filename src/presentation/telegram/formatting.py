"""Shared Presentation-layer formatting helpers.

Extracted from handlers/preview.py in Day 7, when the guided download
flow started needing the exact same preview card — importing a private
`_format_preview` across handler modules would be a smell, duplicating
it would be a DRY violation.
"""

from __future__ import annotations

from html import escape as html_escape

from src.config.settings import Settings
from src.domain.value_objects.media_preview import MediaPreview


def format_help(settings: Settings) -> str:
    """Help text for /help and the ℹ️ button (single source — DRY).

    Built from Settings, not hardcoded lists: the supported-platform
    list is the actual allowlist, the limits are the actual rate-limit
    values. Docs can't drift from behaviour. Day 9 (i18n) will turn
    this into localized templates; the data-driven shape stays.
    """
    platforms = (
        ", ".join(sorted(settings.allowed_domains))
        or "любые сайты, которые поддерживает yt-dlp"
    )
    return (
        "Я скачиваю видео по ссылке с поддерживаемых сайтов.\n\n"
        f"Поддерживаемые платформы:\n{html_escape(platforms)}\n\n"
        "Как пользоваться:\n"
        "1. Нажми «⬇️ Скачать» внизу или просто пришли ссылку сообщением.\n"
        "2. Я покажу превью — название, автора, длительность.\n"
        "3. Нажми «✅ Скачать» под превью, и я пришлю файл сюда же.\n\n"
        "Команды:\n"
        "/preview ссылка — только информация о видео\n"
        "/download ссылка — скачать сразу, без превью\n"
        "/help — это сообщение\n\n"
        "Лимиты:\n"
        f"— до {settings.rate_limit_downloads_per_hour} скачиваний в час\n"
        f"— до {settings.rate_limit_previews_per_minute} превью в минуту\n"
        f"— файлы до {settings.max_deliverable_file_size_mb} МБ"
    )


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "неизвестно"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_preview(preview: MediaPreview) -> str:
    # `title` and `uploader` come from the source site via yt-dlp —
    # untrusted external data. The bot's default parse_mode is HTML
    # (see bot_factory.py), so any stray `<`, `>` or `&` in a real
    # video title would otherwise make Telegram reject the message.
    title = html_escape(preview.title)
    uploader = html_escape(preview.uploader) if preview.uploader else "неизвестно"

    return (
        f"📹 {title}\n"
        f"Автор: {uploader}\n"
        f"Длительность: {format_duration(preview.duration_seconds)}\n"
        f"Тип: {preview.media_type.value}"
    )


def format_retry_after(seconds: int) -> str:
    """Human-friendly rate-limit message. Minutes are rounded up so we
    never promise a shorter wait than reality."""
    if seconds < 60:
        return f"Слишком часто. Попробуй через {seconds} сек."
    minutes = -(-seconds // 60)  # ceil
    return f"Лимит исчерпан. Попробуй через {minutes} мин."
