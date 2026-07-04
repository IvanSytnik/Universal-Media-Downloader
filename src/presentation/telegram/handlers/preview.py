"""/preview <url> — fetch and show media metadata without downloading.

First real contact with yt-dlp in the bot. Deliberately a separate
command (not "any message that looks like a URL") for Day 4 — the
final UX (paste a link, get a preview automatically) is a product
decision to make explicitly later, not something to sneak in as a
side effect of this handler.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message

from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.domain.exceptions import ExtractionError, UnsupportedURLError
from src.domain.value_objects.media_preview import MediaPreview
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.shared.logging import get_logger

router = Router(name="preview")
logger = get_logger(__name__)


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "неизвестно"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_preview(preview: MediaPreview) -> str:
    # `title` and `uploader` come from YouTube/yt-dlp — untrusted external
    # data. The bot's default parse_mode is HTML (see bot.py), so any
    # stray `<`, `>`, or `&` in a real video title would otherwise be
    # interpreted as markup and make Telegram reject the whole message
    # (exactly what happened with the literal "<ссылка>" placeholder in
    # the static help text — same root cause, different data source).
    title = html_escape(preview.title)
    uploader = html_escape(preview.uploader) if preview.uploader else "неизвестно"

    return (
        f"📹 {title}\n"
        f"Автор: {uploader}\n"
        f"Длительность: {_format_duration(preview.duration_seconds)}\n"
        f"Тип: {preview.media_type.value}"
    )


@router.message(lambda m: m.text is not None and m.text.startswith("/preview"))
async def handle_preview(message: Message) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("Использование: /preview ссылка")
        return

    url = parts[1].strip()
    # Day 4: constructed directly here, not injected — YtDlpDownloader
    # has no state/dependencies of its own yet. Revisit if that changes
    # (e.g. a shared thread pool or rate limiter is added later).
    use_case = PreviewDownloadUseCase(YtDlpDownloader())

    try:
        preview = await use_case.execute(url)
    except UnsupportedURLError as exc:
        await message.answer(f"Некорректная ссылка: {html_escape(str(exc))}")
        return
    except ExtractionError as exc:
        await message.answer(f"Не удалось получить информацию: {html_escape(str(exc))}")
        return

    logger.info("preview_shown", url=url, title=preview.title)
    await message.answer(_format_preview(preview))
