"""/language end-to-end at the manager level (Day 9.2).

The command handler writes the override to Redis (via manager.set_locale)
and to Postgres. The critical property is that after set_locale, the SAME
manager resolves the new locale on the NEXT get_locale — i.e. the switch
actually takes effect. That's what this locks in, without needing a full
aiogram dispatcher.
"""

from __future__ import annotations

import pytest
from aiogram.types import User as AiogramUser

from src.presentation.telegram.i18n import UserLocaleManager


def _tg_user(user_id: int, language_code: str | None) -> AiogramUser:
    return AiogramUser(id=user_id, is_bot=False, first_name="T", language_code=language_code)


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def set(self, key: str, value: str) -> None:
        self._store[key] = value.encode()


@pytest.mark.asyncio
async def test_override_takes_effect_on_next_get() -> None:
    redis = FakeRedis()
    mgr = UserLocaleManager(redis=redis, default_locale="en")
    user = _tg_user(42, "ru")  # Telegram insists on ru

    # Before: resolves to what Telegram says.
    assert await mgr.get_locale(event_from_user=user) == "ru"

    # User picks en via /language → handler calls manager.set_locale.
    await mgr.set_locale("en", event_from_user=user)

    # After: the override wins on the very next resolution.
    assert await mgr.get_locale(event_from_user=user) == "en"


@pytest.mark.asyncio
async def test_switch_is_per_user() -> None:
    redis = FakeRedis()
    mgr = UserLocaleManager(redis=redis, default_locale="en")
    a = _tg_user(1, "ru")
    b = _tg_user(2, "ru")

    await mgr.set_locale("en", event_from_user=a)

    # Only user A is switched; B still follows its language_code.
    assert await mgr.get_locale(event_from_user=a) == "en"
    assert await mgr.get_locale(event_from_user=b) == "ru"


@pytest.mark.asyncio
async def test_switch_back_and_forth() -> None:
    redis = FakeRedis()
    mgr = UserLocaleManager(redis=redis, default_locale="en")
    user = _tg_user(7, "ru")

    await mgr.set_locale("en", event_from_user=user)
    assert await mgr.get_locale(event_from_user=user) == "en"
    await mgr.set_locale("ru", event_from_user=user)
    assert await mgr.get_locale(event_from_user=user) == "ru"
