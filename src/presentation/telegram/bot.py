"""Bot and Dispatcher factories.

Kept separate from the entrypoint (src/main.py) so that tests can
import `create_dispatcher()` without starting polling.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher

from src.config.settings import Settings
from src.infrastructure.telegram.bot_factory import create_telegram_bot
from src.presentation.telegram.handlers.basic import router as basic_router
from src.presentation.telegram.handlers.download import router as download_router
from src.presentation.telegram.handlers.preview import router as preview_router
from src.presentation.telegram.handlers.worker import router as worker_router


def create_bot(settings: Settings) -> Bot:
    return create_telegram_bot(settings)


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(basic_router)
    dp.include_router(worker_router)
    dp.include_router(preview_router)
    dp.include_router(download_router)
    return dp
