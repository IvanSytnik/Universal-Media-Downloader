"""Basic handlers: /start, /help, /ping, /health.

Day 9: all replies are localized via the injected ``i18n`` context (the
I18nMiddleware puts it in workflow data under the key ``i18n``, so it's
available by name in any handler, exactly like ``settings``). ``/start``
additionally seeds the new user's ``language`` from the Telegram
``language_code`` so a first-time user is greeted in their own language
even before any explicit ``/language`` choice exists.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram_i18n import I18nContext

from src.config.settings import Settings
from src.domain.interfaces.health_check import HealthCheckPort
from src.presentation.telegram.dependencies import UseCaseProvider
from src.presentation.telegram.formatting import format_help
from src.presentation.telegram.keyboards import main_menu_keyboard
from src.shared.logging import get_logger

router = Router(name="basic")
logger = get_logger(__name__)


@router.message(CommandStart())
async def handle_start(
    message: Message,
    i18n: I18nContext,
    use_cases: UseCaseProvider,
) -> None:
    if message.from_user is None:
        return

    telegram_id = message.from_user.id
    # Seed the persisted language from Telegram's reported UI language.
    # ``i18n.locale`` is already the resolved locale for this update
    # (override → language_code → default), so storing it makes the
    # user's first implicit choice durable for future non-Telegram
    # clients too (Web/API have no language_code to fall back on).
    language = i18n.locale

    async with use_cases.register_user() as use_case:
        user = await use_case.execute(telegram_id, language=language)

    logger.info(
        "start_command",
        telegram_id=telegram_id,
        internal_user_id=str(user.id),
        # Diagnostic (Day 9.2): what Telegram reported vs what we resolved.
        # Confirms locale selection from real traffic — the language_code
        # a client sends often differs from its UI language, which is why
        # /language (explicit override) exists.
        telegram_language_code=(
            message.from_user.language_code if message.from_user else None
        ),
        resolved_locale=i18n.locale,
    )

    await message.answer(
        i18n.get("start-greeting"),
        reply_markup=main_menu_keyboard(i18n),
    )


@router.message(Command("help"))
async def handle_help(message: Message, i18n: I18nContext, settings: Settings) -> None:
    await message.answer(format_help(i18n, settings))


@router.message(lambda m: m.text == "/ping")
async def handle_ping(message: Message) -> None:
    await message.answer("pong")


@router.message(lambda m: m.text == "/health")
async def handle_health(message: Message, i18n: I18nContext, health_check: HealthCheckPort) -> None:
    report = await health_check.check()

    database_error = html_escape(report.database_error) if report.database_error else None
    cache_error = html_escape(report.cache_error) if report.cache_error else None
    ok = i18n.get("health-ok")

    lines = [
        i18n.get("health-postgres", status=ok if report.database_ok else f"❌ {database_error}"),
        i18n.get("health-redis", status=ok if report.cache_ok else f"❌ {cache_error}"),
    ]
    await message.answer("\n".join(lines))

    logger.info("health_check", postgres_ok=report.database_ok, redis_ok=report.cache_ok)
