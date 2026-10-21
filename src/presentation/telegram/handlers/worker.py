"""Worker smoke-test handlers: /worker_ping, /worker_status. Day 9: localized."""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message
from aiogram_i18n import I18nContext

from src.domain.interfaces.ping_result_reader import PingResultReader
from src.presentation.telegram.dependencies import UseCaseProvider
from src.shared.logging import get_logger

router = Router(name="worker")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/worker_ping"))
async def handle_worker_ping(
    message: Message, i18n: I18nContext, use_cases: UseCaseProvider
) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    ping_message = parts[1] if len(parts) > 1 else "hello from bot"

    job_id = await use_cases.trigger_ping_job().execute(ping_message)

    logger.info("worker_ping_enqueued", job_id=job_id, message=ping_message)
    await message.answer(i18n.get("worker-ping-enqueued", jobid=job_id))


@router.message(lambda m: m.text == "/worker_status")
async def handle_worker_status(
    message: Message, i18n: I18nContext, ping_result_reader: PingResultReader
) -> None:
    result = await ping_result_reader.get_last()

    if result is None:
        await message.answer(i18n.get("worker-status-empty"))
        return

    safe_message = html_escape(result.message)
    await message.answer(
        i18n.get("worker-status", message=safe_message, processed=result.processed_at)
    )
