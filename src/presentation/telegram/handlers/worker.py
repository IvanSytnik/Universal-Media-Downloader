"""Worker smoke-test handlers: /worker_ping, /worker_status.

Same rule as always: no business logic in the handler itself. The
handler extracts input, calls the use case (or, for /worker_status,
a direct read — see note below), formats the reply.
"""

from __future__ import annotations

import json
from html import escape as html_escape

from aiogram import Router
from aiogram.types import Message
from arq import ArqRedis

from src.application.use_cases.trigger_ping_job import TriggerPingJobUseCase
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.infrastructure.queue.jobs import LAST_PING_REDIS_KEY
from src.shared.logging import get_logger

router = Router(name="worker")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/worker_ping"))
async def handle_worker_ping(message: Message, arq_pool: ArqRedis) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    ping_message = parts[1] if len(parts) > 1 else "hello from bot"

    use_case = TriggerPingJobUseCase(ArqTaskQueue(arq_pool))
    job_id = await use_case.execute(ping_message)

    logger.info("worker_ping_enqueued", job_id=job_id, message=ping_message)
    await message.answer(
        f"Задача поставлена в очередь.\nJob ID: {job_id}\n\n"
        "Проверь результат через несколько секунд: /worker_status"
    )


@router.message(lambda m: m.text == "/worker_status")
async def handle_worker_status(message: Message, arq_pool: ArqRedis) -> None:
    # Direct Redis read, no use case/repository — this is a debug/ops
    # command reading a status key, not a domain operation. If this
    # grows into real job-status tracking (Day 5+, DownloadRequest.status
    # in Postgres), it moves behind a proper use case + repository then.
    raw = await arq_pool.get(LAST_PING_REDIS_KEY)

    if raw is None:
        await message.answer(
            "Воркер ещё не обработал ни одной ping-задачи.\n"
            "Сначала выполни /worker_ping"
        )
        return

    data = json.loads(raw)
    # `data["message"]` is whatever the user typed after /worker_ping —
    # untrusted input, echoed back through a bot whose default parse_mode
    # is HTML. Must be escaped, same reasoning as preview.py.
    safe_message = html_escape(data["message"])
    await message.answer(
        "Последняя обработанная ping-задача:\n"
        f"Сообщение: {safe_message}\n"
        f"Обработана: {data['processed_at']}"
    )
