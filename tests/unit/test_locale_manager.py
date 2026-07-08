"""UserLocaleManager priority: override (Redis) → language_code → default."""

from __future__ import annotations

import pytest
from aiogram.types import User as AiogramUser

from src.presentation.telegram.i18n import UserLocaleManager


def _tg_user(user_id: int, language_code: str | None) -> AiogramUser:
    return AiogramUser(
        id=user_id, is_bot=False, first_name="Test", language_code=language_code
    )


class FakeRedis:
    def __init__(self, store: dict[str, bytes] | None = None) -> None:
        self._store = store or {}

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value.encode()


@pytest.mark.asyncio
async def test_falls_back_to_default_without_user() -> None:
    mgr = UserLocaleManager(redis=None, default_locale="en")
    assert await mgr.get_locale(event_from_user=None) == "en"


@pytest.mark.asyncio
async def test_uses_telegram_language_code() -> None:
    mgr = UserLocaleManager(redis=FakeRedis(), default_locale="en")
    assert await mgr.get_locale(event_from_user=_tg_user(1, "ru")) == "ru"


@pytest.mark.asyncio
async def test_normalizes_regional_variant() -> None:
    mgr = UserLocaleManager(redis=FakeRedis(), default_locale="ru")
    assert await mgr.get_locale(event_from_user=_tg_user(1, "en-US")) == "en"


@pytest.mark.asyncio
async def test_unsupported_language_falls_back_to_default() -> None:
    mgr = UserLocaleManager(redis=FakeRedis(), default_locale="en")
    # German isn't shipped — must fall through to default, not error.
    assert await mgr.get_locale(event_from_user=_tg_user(1, "de")) == "en"


@pytest.mark.asyncio
async def test_redis_override_wins_over_language_code() -> None:
    redis = FakeRedis({"umd:locale:42": b"en"})
    mgr = UserLocaleManager(redis=redis, default_locale="ru")
    # Telegram says ru, but the explicit override says en → override wins.
    assert await mgr.get_locale(event_from_user=_tg_user(42, "ru")) == "en"


@pytest.mark.asyncio
async def test_invalid_override_ignored() -> None:
    redis = FakeRedis({"umd:locale:42": b"de"})  # unsupported override
    mgr = UserLocaleManager(redis=redis, default_locale="en")
    # Falls through to language_code (ru), not the bogus override.
    assert await mgr.get_locale(event_from_user=_tg_user(42, "ru")) == "ru"


@pytest.mark.asyncio
async def test_set_locale_writes_through_to_redis() -> None:
    redis = FakeRedis()
    mgr = UserLocaleManager(redis=redis, default_locale="en")
    await mgr.set_locale("ru", event_from_user=_tg_user(7, "en"))
    assert await mgr.get_locale(event_from_user=_tg_user(7, "en")) == "ru"
