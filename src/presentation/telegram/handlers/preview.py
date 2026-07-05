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
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.presentation.telegram.formatting import format_preview
from src.shared.logging import get_logger

router = Router(name="preview")
logger = get_logger(__name__)


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
    await message.answer(format_preview(preview))
