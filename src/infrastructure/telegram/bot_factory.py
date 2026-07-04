"""Shared aiogram Bot factory — used by both the polling bot process
(src/presentation/telegram/bot.py) and the worker's notifier
(src/infrastructure/queue/worker_settings.py).

Kept in `infrastructure`, not `presentation`: an aiogram `Bot` instance
is an infrastructure-level concern (it's an HTTP client for Telegram's
API) regardless of whether the caller uses it for long polling or for
one-off notifications. Presentation-layer code building a Dispatcher
around it is a separate concern from constructing the client itself.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from src.config.settings import Settings


def create_telegram_bot(settings: Settings) -> Bot:
    """Builds a Bot pointed at api.telegram.org, or at a local Bot API
    server (see PROJECT_SPEC §6.2 — chosen over quality-reduction or
    S3+link for large-file delivery) when `settings.use_local_bot_api`
    is set. The local server raises the upload limit from 50MB to
    2000MB; everything else about how `Bot` is used stays the same.
    """
    session: AiohttpSession | None = None
    if settings.use_local_bot_api:
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.local_bot_api_base_url, is_local=True)
        )

    return Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
