"""Custom aiogram filters."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from src.config.settings import Settings


class AdminOnly(BaseFilter):
    """Passes only for users listed in ``ADMIN_TELEGRAM_IDS``.

    Fails closed: no sender (channel posts, anonymous admins) or an empty
    allowlist means no access. ``settings`` is injected from workflow data
    by name, like in handlers.
    """

    async def __call__(self, message: Message, settings: Settings) -> bool:
        user = message.from_user
        return user is not None and user.id in settings.admin_telegram_ids_set
