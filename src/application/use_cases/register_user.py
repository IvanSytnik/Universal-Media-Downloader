"""RegisterUserUseCase — get-or-create a User by their Telegram ID.

This is the first use case in the project. It depends only on the
domain interface (`UserRepository`), never on the SQLAlchemy
implementation directly — that's what makes it testable without a
database (see tests/unit/test_register_user_use_case.py, which uses
an in-memory fake).
"""

from __future__ import annotations

from src.domain.entities.user import User
from src.domain.interfaces.user_repository import UserRepository


class RegisterUserUseCase:
    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    async def execute(self, telegram_id: int) -> User:
        existing = await self._user_repository.get_by_telegram_id(telegram_id)
        if existing is not None:
            return existing

        new_user = User.create_from_telegram(telegram_id)
        return await self._user_repository.create(new_user)
