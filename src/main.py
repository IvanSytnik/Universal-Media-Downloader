"""Application entrypoint — Day 3: Telegram bot + DB + task queue pool.

The worker process has its own entrypoint (run via the `arq` CLI against
src/infrastructure/queue/worker_settings.py:WorkerSettings), not this file.
Bot and worker are separate processes on purpose — see PROJECT_SPEC §11.
"""

from __future__ import annotations

import asyncio

from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis

from src.config.settings import Settings, get_settings
from src.infrastructure.database.engine import create_engine, create_session_factory
from src.infrastructure.preview_context.redis_preview_context_store import (
    RedisPreviewContextStore,
)
from src.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter
from src.presentation.telegram.bot import create_bot, create_dispatcher
from src.shared.logging import configure_logging, get_logger


async def main() -> None:
    settings: Settings = get_settings()
    configure_logging(log_level=settings.log_level, environment=settings.environment)
    logger = get_logger(__name__)

    logger.info("starting_bot", environment=settings.environment)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    arq_pool = await create_pool(
        RedisSettings(
            host=settings.redis_host,
            port=settings.redis_port,
            database=settings.redis_db,
        )
    )

    # One shared Redis client for both FSM state (aiogram RedisStorage —
    # survives restarts, ready for multiple bot instances) and the
    # preview-context store (token → URL for inline confirm buttons).
    redis_client: Redis = Redis.from_url(settings.redis_dsn)
    fsm_storage = RedisStorage(redis=redis_client)
    preview_store = RedisPreviewContextStore(
        redis=redis_client,
        ttl_seconds=settings.preview_context_ttl_seconds,
    )
    rate_limiter = RedisRateLimiter(redis=redis_client)

    bot = create_bot(settings)
    dp = create_dispatcher(storage=fsm_storage)

    # Blue "menu" button next to the input field (Day 8). Idempotent —
    # safe to call on every startup.
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="download", description="Скачать по ссылке"),
            BotCommand(command="preview", description="Информация о видео"),
            BotCommand(command="help", description="Помощь и лимиты"),
        ]
    )

    try:
        # `settings=`, `session_factory=`, `arq_pool=`, `preview_store=`
        # here are what make those parameters available by name in any
        # handler (see handlers/basic.py, handlers/download_flow.py).
        await dp.start_polling(
            bot,
            settings=settings,
            session_factory=session_factory,
            arq_pool=arq_pool,
            preview_store=preview_store,
            rate_limiter=rate_limiter,
        )
    finally:
        await arq_pool.close()
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
