"""RegisterUserUseCase tests using an in-memory fake — no database at all.

This is the "domain/application must be 100% covered, cheap to test"
part of the testing strategy from PROJECT_SPEC §7: this test runs in
milliseconds and needs nothing but Python.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from src.application.use_cases.register_user import RegisterUserUseCase
from src.domain.entities.user import User


class FakeUserRepository:
    """In-memory stand-in for UserRepository (satisfies the Protocol structurally)."""

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
