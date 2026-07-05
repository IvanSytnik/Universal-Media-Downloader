"""Bot and Dispatcher factories.

Kept separate from the entrypoint (src/main.py) so that tests can
import `create_dispatcher()` without starting polling.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage

from src.config.settings import Settings
from src.infrastructure.telegram.bot_factory import create_telegram_bot
from src.presentation.telegram.handlers.basic import router as basic_router
from src.presentation.telegram.handlers.download import router as download_router
from src.presentation.telegram.handlers.download_flow import router as download_flow_router
from src.presentation.telegram.handlers.preview import router as preview_router
from src.presentation.telegram.handlers.worker import router as worker_router


def create_bot(settings: Settings) -> Bot:
    return create_telegram_bot(settings)


def create_dispatcher(storage: BaseStorage | None = None) -> Dispatcher:
    """`storage` backs aiogram's FSM. In production main.py passes a
    RedisStorage (state survives restarts / multiple instances); tests
    can omit it and get aiogram's default MemoryStorage.

    Router order matters: download_flow_router goes LAST because its
    plain-URL handler matches any message starting with http(s)://.
    Command routers must get first pick, so "/preview https://..." is
    handled as a command, never as a bare URL.
    """
    dp = Dispatcher(storage=storage)
    dp.include_router(basic_router)
    dp.include_router(worker_router)
    dp.include_router(preview_router)
    dp.include_router(download_router)
    dp.include_router(download_flow_router)
    return dp
