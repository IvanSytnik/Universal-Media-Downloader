"""/download <url> — the real thing: enqueues an actual download.

Returns immediately (the handler only touches the DB and the queue —
see RequestDownloadUseCase). The worker sends the file directly to the
user later via NotifierPort, not through this handler — that's why
there's no "wait for the result" logic here.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.use_cases.request_download import RequestDownloadUseCase
from src.domain.exceptions import UnsupportedURLError
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.shared.logging import get_logger

router = Router(name="download")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/download"))
async def handle_download(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    arq_pool: ArqRedis,
) -> None:
    if message.from_user is None:
        return

    text = message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /download ссылка")
        return

    url = parts[1].strip()
    telegram_id = message.from_user.id

    async with session_scope(session_factory) as session:
        use_case = RequestDownloadUseCase(
            user_repository=SqlAlchemyUserRepository(session),
            download_request_repository=SqlAlchemyDownloadRequestRepository(session),
            task_queue=ArqTaskQueue(arq_pool),
        )
        try:
            request = await use_case.execute(telegram_id, url)
        except UnsupportedURLError as exc:
            await message.answer(f"Некорректная ссылка: {html_escape(str(exc))}")
            return

    logger.info("download_requested", request_id=str(request.id), telegram_id=telegram_id)
    await message.answer(
        "Скачивание начато — это может занять от нескольких секунд до нескольких минут "
        "в зависимости от размера видео.\n"
        "Пришлю файл сюда же, когда будет готово."
    )
