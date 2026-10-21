"""Operational commands: /health, /worker_ping, /worker_status. Admins only.

Access is granted by ``ADMIN_TELEGRAM_IDS`` (see ``AdminOnly``). For anyone
else the commands behave as if they did not exist: the denial handler at
the bottom consumes the update silently and logs the attempt. Consuming it
matters — an unhandled "/health" would fall through to the routers below
(e.g. the URL-waiting state of the download flow) and get a confusing
reply.

``/health`` reports a clean per-component status only. The raw failure
reason (driver exception text, hostnames) is logged by the health check
implementation and never sent to a chat, not even to an admin: chat
history is a far wider audience than the log pipeline.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram_i18n import I18nContext

from src.domain.interfaces.health_check import HealthCheckPort
from src.domain.interfaces.ping_result_reader import PingResultReader
from src.presentation.telegram.dependencies import UseCaseProvider
from src.presentation.telegram.filters import AdminOnly
from src.shared.logging import get_logger

router = Router(name="admin")
logger = get_logger(__name__)

ADMIN_COMMANDS: tuple[str, ...] = ("health", "worker_ping", "worker_status")


@router.message(Command("health"), AdminOnly())
async def handle_health(message: Message, i18n: I18nContext, health_check: HealthCheckPort) -> None:
    report = await health_check.check()

    ok = i18n.get("health-ok")
    fail = i18n.get("health-fail")
    lines = [
        i18n.get("health-postgres", status=ok if report.database_ok else fail),
        i18n.get("health-redis", status=ok if report.cache_ok else fail),
    ]
    await message.answer("\n".join(lines))

    logger.info("health_check", postgres_ok=report.database_ok, redis_ok=report.cache_ok)


@router.message(Command("worker_ping"), AdminOnly())
async def handle_worker_ping(
    message: Message, i18n: I18nContext, use_cases: UseCaseProvider
) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    ping_message = parts[1] if len(parts) > 1 else "hello from bot"

    job_id = await use_cases.trigger_ping_job().execute(ping_message)

    logger.info("worker_ping_enqueued", job_id=job_id, message=ping_message)
    await message.answer(i18n.get("worker-ping-enqueued", jobid=job_id))


@router.message(Command("worker_status"), AdminOnly())
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


@router.message(Command(*ADMIN_COMMANDS))
async def handle_admin_command_denied(message: Message) -> None:
    """Reached only when ``AdminOnly`` rejected the sender above."""
    logger.warning(
        "admin_command_denied",
        telegram_id=message.from_user.id if message.from_user else None,
        command=(message.text or "").split(maxsplit=1)[0],
    )
