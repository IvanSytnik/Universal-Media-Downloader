"""/language — explicit locale switch (Day 9.2).

Why this exists: Telegram's ``from_user.language_code`` is only a *hint*
and can't be changed from the client reliably (it reflects the account's
language setting, often "ru" regardless of the app UI). So the automatic
locale detection (language_code → default) can leave a user stuck on a
language they can't change. This command is the durable, user-driven
override that actually lets them pick.

Persistence is two-tier, matching the manager's read path (see i18n.py):
- Redis (via ``manager.set_locale``) — the hot-path cache the locale
  manager reads on every update, so the switch takes effect on the NEXT
  update immediately.
- Postgres (via ``UserRepository.set_language``) — durable source of
  truth, survives a Redis eviction; a future cache-miss path can re-warm
  Redis from it.

Both are written; if only Redis were written the choice would silently
revert on eviction, if only Postgres were written the manager (which
reads Redis, deliberately not the DB on the hot path) wouldn't see it
until a re-warm. Writing both keeps the two stores consistent.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram_i18n import I18nContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.presentation.telegram.i18n import SUPPORTED_LOCALES
from src.presentation.telegram.keyboards import (
    CB_LANG_PREFIX,
    language_picker_keyboard,
    main_menu_keyboard,
)
from src.shared.logging import get_logger

router = Router(name="language")
logger = get_logger(__name__)


@router.message(Command("language"))
async def handle_language_command(message: Message, i18n: I18nContext) -> None:
    # Prompt is intentionally bilingual (see FTL) so it's understandable
    # whatever locale the user is currently (maybe wrongly) on.
    await message.answer(
        i18n.get("language-prompt"),
        reply_markup=language_picker_keyboard(i18n),
    )


@router.callback_query(F.data.startswith(CB_LANG_PREFIX))
async def handle_language_choice(
    callback: CallbackQuery,
    i18n: I18nContext,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    chosen = (callback.data or "")[len(CB_LANG_PREFIX):]
    if chosen not in SUPPORTED_LOCALES:
        # Defensive: only ever produced by our own keyboard, but never
        # trust callback_data blindly.
        await callback.answer()
        return

    telegram_id = callback.from_user.id

    # 1. Hot-path cache (Redis) — effective from the next update. set_locale
    #    is a no-op if the manager has no Redis (e.g. in tests), which is
    #    fine: the DB write below is still the durable record.
    await i18n.set_locale(chosen)

    # 2. Durable store (Postgres).
    async with session_scope(session_factory) as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.set_language(telegram_id, chosen)

    logger.info("language_changed", telegram_id=telegram_id, locale=chosen)

    # 3. Confirm in the NEWLY chosen language. The i18n context for THIS
    #    update still holds the old locale (middleware resolved it before
    #    the handler ran), so we pass the chosen locale explicitly rather
    #    than relying on the context locale — same "always pass a locale
    #    outside a fresh request context" rule that bit us in 9.1.
    if isinstance(callback.message, Message):
        await callback.message.answer(
            i18n.get("language-changed", locale=chosen),
            reply_markup=main_menu_keyboard(i18n, chosen),
        )
    await callback.answer()
