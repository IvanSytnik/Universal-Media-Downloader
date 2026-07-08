"""Repository interface for User. Domain layer — no implementation here."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.domain.entities.user import User


class UserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...

    async def create(self, user: User) -> User: ...

    async def set_language(self, telegram_id: int, language: str | None) -> User | None:
        """Update a user's explicit locale override.

        Returns the updated ``User`` or ``None`` if no user with that
        ``telegram_id`` exists. Added in Day 9 as the persistence contract
        for a future ``/language`` command; the command itself is
        intentionally out of Day 9 scope, but shipping the port now avoids
        a second migration/interface churn when it lands.
        """
        ...
