"""SetUserLanguageUseCase delegates to the UserRepository port."""

from __future__ import annotations

from uuid import UUID

import pytest

from src.application.use_cases.set_user_language import SetUserLanguageUseCase
from src.domain.entities.user import User


class _FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self._by_telegram_id = {u.telegram_id: u for u in users}
        self.calls: list[tuple[int, str | None]] = []

    async def get_by_id(self, user_id: UUID) -> User | None:  # pragma: no cover - unused
        raise NotImplementedError

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:  # pragma: no cover
        raise NotImplementedError

    async def create(self, user: User) -> User:  # pragma: no cover - unused
        raise NotImplementedError

    async def set_language(self, telegram_id: int, language: str | None) -> User | None:
        self.calls.append((telegram_id, language))
        user = self._by_telegram_id.get(telegram_id)
        if user is None:
            return None
        user.language = language
        return user


@pytest.mark.asyncio
async def test_sets_language_for_existing_user() -> None:
    repo = _FakeUserRepository([User.create_from_telegram(42, language="en")])

    updated = await SetUserLanguageUseCase(repo).execute(42, "ru")

    assert repo.calls == [(42, "ru")]
    assert updated is not None
    assert updated.language == "ru"


@pytest.mark.asyncio
async def test_unknown_user_returns_none() -> None:
    repo = _FakeUserRepository([])

    assert await SetUserLanguageUseCase(repo).execute(7, "en") is None
    assert repo.calls == [(7, "en")]
