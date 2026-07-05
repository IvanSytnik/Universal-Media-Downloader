"""Shared Presentation-layer formatting helpers.

Extracted from handlers/preview.py in Day 7, when the guided download
flow started needing the exact same preview card — importing a private
`_format_preview` across handler modules would be a smell, duplicating
it would be a DRY violation.
"""

from __future__ import annotations

from html import escape as html_escape

from src.domain.value_objects.media_preview import MediaPreview


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
