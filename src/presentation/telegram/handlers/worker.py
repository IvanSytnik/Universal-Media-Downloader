"""Worker smoke-test handlers: /worker_ping, /worker_status. Day 9: localized."""

from __future__ import annotations

import json
from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message
from aiogram_i18n import I18nContext
from arq import ArqRedis

from src.application.use_cases.trigger_ping_job import TriggerPingJobUseCase
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.infrastructure.queue.jobs import LAST_PING_REDIS_KEY
from src.shared.logging import get_logger

router = Router(name="worker")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/worker_ping"))
async def handle_worker_ping(message: Message, i18n: I18nContext, arq_pool: ArqRedis) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    ping_message = parts[1] if len(parts) > 1 else "hello from bot"

    use_case = TriggerPingJobUseCase(ArqTaskQueue(arq_pool))
    job_id = await use_case.execute(ping_message)

    logger.info("worker_ping_enqueued", job_id=job_id, message=ping_message)
    await message.answer(i18n.get("worker-ping-enqueued", jobid=job_id))


@router.message(lambda m: m.text == "/worker_status")
async def handle_worker_status(message: Message, i18n: I18nContext, arq_pool: ArqRedis) -> None:
    raw = await arq_pool.get(LAST_PING_REDIS_KEY)

    if raw is None:
        await message.answer(i18n.get("worker-status-empty"))
        return

    data = json.loads(raw)
    safe_message = html_escape(data["message"])
    await message.answer(
        i18n.get("worker-status", message=safe_message, processed=data["processed_at"])
    )
