"""/download <url> — enqueues an actual download. Day 9: localized."""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message
from aiogram_i18n import I18nContext
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.use_cases.request_download import RequestDownloadUseCase
from src.config.settings import Settings
from src.domain.exceptions import UnsupportedURLError
from src.domain.interfaces.rate_limiter import RateLimiterPort
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.presentation.telegram.formatting import format_retry_after
from src.shared.logging import get_logger

router = Router(name="download")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/download"))
async def handle_download(
    message: Message,
    i18n: I18nContext,
    session_factory: async_sessionmaker[AsyncSession],
    arq_pool: ArqRedis,
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

    async with session_scope(session_factory) as session:
        use_case = RequestDownloadUseCase(
            user_repository=SqlAlchemyUserRepository(session),
            download_request_repository=SqlAlchemyDownloadRequestRepository(session),
            task_queue=ArqTaskQueue(arq_pool),
        )
        try:
            request = await use_case.execute(telegram_id, url)
        except UnsupportedURLError as exc:
            await message.answer(i18n.get("error-bad-url", reason=html_escape(str(exc))))
            return

    logger.info("download_requested", request_id=str(request.id), telegram_id=telegram_id)
    await message.answer(i18n.get("download-started"))
