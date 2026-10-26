"""Bot process entrypoint and composition root.

Builds every long-lived resource (engine, Redis, arq pool, i18n core),
wires concrete infrastructure adapters behind domain ports and the
``UseCaseProvider`` (see ``src/composition.py``), and injects them into
the dispatcher as workflow data. This module and ``src/composition.py``
are the only places in the bot process allowed to import infrastructure;
``tests/unit/test_architecture.py`` enforces that for ``src/presentation``.
"""

from __future__ import annotations

import asyncio
import contextlib

from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis

from src.application.policies.format_policy import FormatPolicy
from src.composition import SqlAlchemyUseCaseProvider
from src.config.settings import Settings, get_settings
from src.domain.value_objects.format_kind import FormatKind
from src.infrastructure.database.engine import create_engine, create_session_factory
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.infrastructure.health import ConnectivityHealthCheck
from src.infrastructure.preview_context.redis_preview_context_store import (
    RedisPreviewContextStore,
)
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.infrastructure.queue.ping_result_reader import RedisPingResultReader
from src.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter
from src.infrastructure.telegram.bot_factory import create_telegram_bot
from src.presentation.telegram.bot import (
    collect_button_translations,
    create_dispatcher,
)
from src.presentation.telegram.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    create_i18n_core,
    create_i18n_middleware,
)
from src.presentation.telegram.progress_listener import TelegramProgressListener
from src.shared.logging import configure_logging, get_logger

# Menu-command FTL keys, localized per locale via set_my_commands scopes.
_MENU_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "cmd-start"),
    ("download", "cmd-download"),
    ("preview", "cmd-preview"),
    ("language", "cmd-language"),
    ("help", "cmd-help"),
)


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

    redis_client: Redis = Redis.from_url(settings.redis_dsn)
    fsm_storage = RedisStorage(redis=redis_client)
    preview_store = RedisPreviewContextStore(
        redis=redis_client,
        ttl_seconds=settings.preview_context_ttl_seconds,
    )
    rate_limiter = RedisRateLimiter(redis=redis_client)
    health_check = ConnectivityHealthCheck(settings)
    ping_result_reader = RedisPingResultReader(redis=redis_client)
    # One policy instance for both readers: the use case enforces it, the
    # handlers render buttons from it (workflow data `format_policy`).
    format_policy = FormatPolicy(
        {
            extractor: [FormatKind(kind) for kind in kinds]
            for extractor, kinds in settings.disabled_formats.items()
        }
    )
    use_cases = SqlAlchemyUseCaseProvider(
        session_factory=session_factory,
        task_queue=ArqTaskQueue(arq_pool),
        downloader=YtDlpDownloader(),
        format_policy=format_policy,
    )

    # i18n: build the core, start it (loads FTL for every locale), then
    # derive the button-translation sets from the SAME started core so
    # the routing filters and the rendered keyboards can't disagree.
    i18n_core = create_i18n_core()
    await i18n_core.startup()
    i18n_middleware = create_i18n_middleware(i18n_core, redis=redis_client)
    button_translations = collect_button_translations(i18n_core)

    bot = create_telegram_bot(settings)
    dp = create_dispatcher(
        i18n_middleware=i18n_middleware,
        button_translations=button_translations,
        storage=fsm_storage,
    )

    # Localized blue "menu" button. One set_my_commands call per locale
    # (language_code scope); the default set (no language_code) uses the
    # configured default locale so users with an unsupported UI language
    # still get a sensible menu.
    for locale in SUPPORTED_LOCALES:
        await bot.set_my_commands(
            [
                BotCommand(command=cmd, description=i18n_core.get(key, locale))
                for cmd, key in _MENU_COMMANDS
            ],
            language_code=locale,
        )
    await bot.set_my_commands(
        [
            BotCommand(command=cmd, description=i18n_core.get(key, DEFAULT_LOCALE))
            for cmd, key in _MENU_COMMANDS
        ]
    )

    # Day 11B: long-lived umd:progress:* listener, same process/same bot
    # (Option A, TASK_Day11B.md) — reuses redis_client (a pubsub()
    # connection is a separate connection from the same pool, standard
    # usage) and the already-started i18n_core for explicit-locale
    # rendering (bug #10 — no I18nContext exists in this background task).
    progress_listener = TelegramProgressListener(
        bot=bot,
        redis=redis_client,
        i18n_core=i18n_core,
        default_locale=DEFAULT_LOCALE,
    )
    listener_task = asyncio.create_task(progress_listener.run())

    try:
        await dp.start_polling(
            bot,
            settings=settings,
            use_cases=use_cases,
            preview_store=preview_store,
            format_policy=format_policy,
            rate_limiter=rate_limiter,
            health_check=health_check,
            ping_result_reader=ping_result_reader,
        )
    finally:
        listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener_task
        await arq_pool.close()
        await redis_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
