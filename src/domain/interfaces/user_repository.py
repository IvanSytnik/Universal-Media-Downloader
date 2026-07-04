"""Repository interface for User. Domain layer — no implementation here.

Implemented by src/infrastructure/database/repositories/user_repository.py.
Using typing.Protocol (structural typing) instead of ABC — no inheritance
required from implementations, keeps infrastructure decoupled from domain
at the class-hierarchy level too, not just at the import level.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.domain.entities.user import User


class UserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...

    async def create(self, user: User) -> User: ...
