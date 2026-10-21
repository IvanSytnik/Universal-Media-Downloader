"""SetUserLanguageUseCase — persist a user's explicit locale override.

The durable half of ``/language``: the presentation layer also writes the
hot-path Redis cache through the i18n manager, but Postgres (via the
``UserRepository`` port) is the source of truth that survives eviction.
"""

from __future__ import annotations

from src.domain.entities.user import User
from src.domain.interfaces.user_repository import UserRepository


class SetUserLanguageUseCase:
    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    async def execute(self, telegram_id: int, language: str | None) -> User | None:
        """Returns the updated user, or ``None`` if no such user exists."""
        return await self._user_repository.set_language(telegram_id, language)
