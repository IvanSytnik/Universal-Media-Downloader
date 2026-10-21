"""/download <url> — enqueues an actual download. Day 9: localized.

Day 11B: progress needs a message to edit, so the "download-started"
status message is now sent BEFORE enqueueing (not after) and its
(chat_id, message_id) is threaded into RequestDownloadUseCase; on a
validation failure that same message is edited into the error instead of
a second message being sent. Trade-off: an invalid link now briefly
shows "download started" before flipping to the error, whereas before
the error appeared immediately — accepted so progress always has
somewhere to go, consistent with download_flow.py's guided path.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message
from aiogram_i18n import I18nContext

from src.config.settings import Settings
from src.domain.exceptions import UnsupportedURLError
from src.domain.interfaces.rate_limiter import RateLimiterPort
from src.presentation.telegram.dependencies import UseCaseProvider
from src.presentation.telegram.formatting import format_retry_after
from src.shared.logging import get_logger

router = Router(name="download")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/download"))
async def handle_download(
    message: Message,
    i18n: I18nContext,
    use_cases: UseCaseProvider,
    settings: Settings,
    rate_limiter: RateLimiterPort,
) -> None:
    if message.from_user is None:
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(i18n.get("download-usage"))
        return

    url = parts[1].strip()
    telegram_id = message.from_user.id

    verdict = await rate_limiter.acquire(
        key=f"download:{telegram_id}",
        limit=settings.rate_limit_downloads_per_hour,
        window_seconds=3600,
    )
    if not verdict.allowed:
        logger.info("download_rate_limited", telegram_id=telegram_id)
        await message.answer(format_retry_after(i18n, verdict.retry_after_seconds))
        return

    status_message = await message.answer(i18n.get("download-started"))

    async with use_cases.request_download() as use_case:
        try:
            request = await use_case.execute(
                telegram_id,
                url,
                chat_id=status_message.chat.id,
                message_id=status_message.message_id,
            )
        except UnsupportedURLError as exc:
            await status_message.edit_text(i18n.get("error-bad-url", reason=html_escape(str(exc))))
            return

    logger.info("download_requested", request_id=str(request.id), telegram_id=telegram_id)
