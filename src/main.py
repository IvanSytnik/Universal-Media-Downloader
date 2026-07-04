"""Application entrypoint — Day 3: Telegram bot + DB + task queue pool.

The worker process has its own entrypoint (run via the `arq` CLI against
src/infrastructure/queue/worker_settings.py:WorkerSettings), not this file.
Bot and worker are separate processes on purpose — see PROJECT_SPEC §11.
"""

from __future__ import annotations

import asyncio

from arq.connections import RedisSettings, create_pool

from src.config.settings import Settings, get_settings
from src.infrastructure.database.engine import create_engine, create_session_factory
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

    bot = create_bot(settings)
    dp = create_dispatcher()

    try:
        # `settings=`, `session_factory=`, `arq_pool=` here are what make
        # those parameters available by name in any handler (see
        # handlers/basic.py and handlers/worker.py).
        await dp.start_polling(
            bot,
            settings=settings,
            session_factory=session_factory,
            arq_pool=arq_pool,
        )
    finally:
        await arq_pool.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
