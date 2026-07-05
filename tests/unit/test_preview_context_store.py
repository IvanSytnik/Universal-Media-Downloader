"""RedisPreviewContextStore — tested against a minimal in-memory fake
implementing exactly the Redis surface the store uses (set/get/delete).
TTL expiry itself is Redis's job (SET ... EX), so we verify the TTL is
*passed*, not that time actually elapses.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.preview_context.redis_preview_context_store import (
    RedisPreviewContextStore,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.last_ttl: int | None = None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value.encode("utf-8")
        self.last_ttl = ex

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


def _store(fake: _FakeRedis, ttl: int = 600) -> RedisPreviewContextStore:
    redis: Any = fake  # duck-typed stand-in for redis.asyncio.Redis
    return RedisPreviewContextStore(redis=redis, ttl_seconds=ttl)


async def test_save_returns_short_callback_safe_token() -> None:
    fake = _FakeRedis()
    token = await _store(fake).save("https://youtube.com/watch?v=abc")
    # 32-char hex + "dl:" prefix must fit Telegram's 64-byte limit.
    assert len(token) == 32
    assert token.isalnum()


async def test_roundtrip_save_get() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    url = "https://youtube.com/watch?v=abc"
    token = await store.save(url)
    assert await store.get(token) == url


async def test_get_unknown_token_returns_none() -> None:
    fake = _FakeRedis()
    assert await _store(fake).get("deadbeef" * 4) is None


async def test_delete_removes_entry() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    token = await store.save("https://youtube.com/x")
    await store.delete(token)
    assert await store.get(token) is None


async def test_delete_is_idempotent() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    await store.delete("nonexistent")  # must not raise


async def test_ttl_is_passed_to_redis() -> None:
    fake = _FakeRedis()
    await _store(fake, ttl=123).save("https://youtube.com/x")
    assert fake.last_ttl == 123


async def test_tokens_are_unique() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    tokens = {await store.save("https://youtube.com/x") for _ in range(50)}
    assert len(tokens) == 50
