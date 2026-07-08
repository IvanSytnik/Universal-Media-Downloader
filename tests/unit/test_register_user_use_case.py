from __future__ import annotations

from uuid import UUID

import pytest

from src.application.use_cases.register_user import RegisterUserUseCase
from src.domain.entities.user import User


class FakeUserRepository:
    def __init__(self) -> None:
        self._users: dict[UUID, User] = {}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        for user in self._users.values():
            if user.telegram_id == telegram_id:
                return user
        return None

    async def create(self, user: User) -> User:
        self._users[user.id] = user
        return user

    async def set_language(self, telegram_id: int, language: str | None) -> User | None:
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            return None
        user.language = language
        return user


@pytest.mark.asyncio
async def test_creates_new_user_when_not_found() -> None:
    repo = FakeUserRepository()
    use_case = RegisterUserUseCase(repo)
    user = await use_case.execute(telegram_id=12345)
    assert user.telegram_id == 12345
    assert await repo.get_by_telegram_id(12345) == user


@pytest.mark.asyncio
async def test_returns_existing_user_without_creating_duplicate() -> None:
    repo = FakeUserRepository()
    use_case = RegisterUserUseCase(repo)
    first = await use_case.execute(telegram_id=999)
    second = await use_case.execute(telegram_id=999)
    assert first.id == second.id
    assert len(repo._users) == 1


@pytest.mark.asyncio
async def test_seeds_language_on_creation() -> None:
    repo = FakeUserRepository()
    use_case = RegisterUserUseCase(repo)
    user = await use_case.execute(telegram_id=7, language="ru")
    assert user.language == "ru"


@pytest.mark.asyncio
async def test_existing_user_language_not_overwritten() -> None:
    # A returning user's stored language must win over whatever the
    # current Telegram language_code says — get_by_telegram_id short
    # circuits before we ever look at the new language argument.
    repo = FakeUserRepository()
    use_case = RegisterUserUseCase(repo)
    first = await use_case.execute(telegram_id=7, language="ru")
    second = await use_case.execute(telegram_id=7, language="en")
    assert second.id == first.id
    assert second.language == "ru"
