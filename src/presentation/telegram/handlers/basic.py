"""Basic handlers: /start, /ping, /health.

`/start` is no longer just a greeting (Day 2) — it registers the user
via RegisterUserUseCase. It still doesn't contain business logic itself:
it extracts input, calls the use case, formats the reply. That's the
whole job of a Presentation-layer handler.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.use_cases.register_user import RegisterUserUseCase
from src.config.settings import Settings
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.infrastructure.health import run_health_check
from src.presentation.telegram.keyboards import main_menu_keyboard
from src.shared.logging import get_logger

router = Router(name="basic")
logger = get_logger(__name__)


@router.message(CommandStart())
async def handle_start(message: Message, session_factory: async_sessionmaker[AsyncSession]) -> None:
    # `session_factory` is injected the same way `settings` is — via
    # dp.start_polling(bot, session_factory=..., settings=...) in main.py.
    if message.from_user is None:
        # Telegram messages can technically arrive without a `from_user`
        # (e.g. channel posts). We only handle user DMs here.
        return

    telegram_id = message.from_user.id

    async with session_scope(session_factory) as session:
        use_case = RegisterUserUseCase(SqlAlchemyUserRepository(session))
        user = await use_case.execute(telegram_id)

    logger.info("start_command", telegram_id=telegram_id, internal_user_id=str(user.id))

    await message.answer(
        "Привет! Это Universal Media Downloader.\n\n"
        "Пришли ссылку на видео (YouTube, TikTok, Instagram и другие) — "
        "покажу превью и скачаю по подтверждению.\n\n"
        "Или воспользуйся кнопками ниже:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(lambda m: m.text == "/ping")
async def handle_ping(message: Message) -> None:
    await message.answer("pong")


@router.message(lambda m: m.text == "/health")
async def handle_health(message: Message, settings: Settings) -> None:
    # `settings` is injected by aiogram via workflow data — see main.py,
    # where it's passed into dp.start_polling(bot, settings=settings).
    # Never instantiate Settings() inside a handler: it would re-read
    # the environment on every message instead of using the single
    # instance created once at startup.
    status = await run_health_check(settings)

    # Exception messages are not fully under our control (driver/library
    # text) — escape before inserting into an HTML parse_mode message,
    # same reasoning as preview.py and worker.py.
    postgres_error = html_escape(status.postgres_error) if status.postgres_error else None
    redis_error = html_escape(status.redis_error) if status.redis_error else None

    lines = [
        f"Postgres: {'✅ OK' if status.postgres_ok else f'❌ {postgres_error}'}",
        f"Redis: {'✅ OK' if status.redis_ok else f'❌ {redis_error}'}",
    ]
    await message.answer("\n".join(lines))

    logger.info(
        "health_check",
        postgres_ok=status.postgres_ok,
        redis_ok=status.redis_ok,
    )
