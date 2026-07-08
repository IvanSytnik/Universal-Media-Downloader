"""Bot and Dispatcher factories. Day 9: i18n wiring.

The dispatcher now installs the I18nMiddleware (so every handler gets an
``i18n`` context) and stashes the precomputed button-translation sets in
workflow data (so the text-routed reply-keyboard filters can match a tap
in any locale — decision 3A). Both are done here rather than in main.py
so tests can build a fully i18n-capable dispatcher without starting
polling.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram_i18n import I18nMiddleware

from src.config.settings import Settings
from src.infrastructure.telegram.bot_factory import create_telegram_bot
from src.presentation.telegram.handlers.basic import router as basic_router
from src.presentation.telegram.handlers.download import router as download_router
from src.presentation.telegram.handlers.download_flow import router as download_flow_router
from src.presentation.telegram.handlers.language import router as language_router
from src.presentation.telegram.handlers.preview import router as preview_router
from src.presentation.telegram.handlers.worker import router as worker_router
from src.presentation.telegram.i18n import collect_button_translations


def create_bot(settings: Settings) -> Bot:
    return create_telegram_bot(settings)


def create_dispatcher(
    i18n_middleware: I18nMiddleware,
    button_translations: dict[str, frozenset[str]],
    storage: BaseStorage | None = None,
) -> Dispatcher:
    """Build the dispatcher.

    ``i18n_middleware`` — already constructed over a started core (its
    locales are loaded), so ``button_translations`` — derived from that
    same core — is consistent with what the middleware will render.

    Router order matters: download_flow_router goes LAST because its
    plain-URL handler matches any http(s):// message; command routers
    must get first pick.
    """
    dp = Dispatcher(storage=storage)
    # Injected into every handler/filter by name (workflow data), exactly
    # like settings/session_factory are in main.py.
    dp["button_translations"] = button_translations

    i18n_middleware.setup(dispatcher=dp)

    dp.include_router(basic_router)
    dp.include_router(language_router)
    dp.include_router(worker_router)
    dp.include_router(preview_router)
    dp.include_router(download_router)
    dp.include_router(download_flow_router)
    return dp


# Re-exported for main.py so it doesn't need to import from i18n directly.
__all__ = ["create_bot", "create_dispatcher", "collect_button_translations"]
