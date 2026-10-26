"""RedisPreviewContextStore — tested against a minimal in-memory fake
implementing exactly the Redis surface the store uses
(set/get/delete/getdel).
TTL expiry itself is Redis's job (SET ... EX), so we verify the TTL is
*passed*, not that time actually elapses.
"""

from __future__ import annotations

from typing import Any

import pytest
import structlog

from src.domain.value_objects.preview_context import PreviewContext
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

    async def getdel(self, key: str) -> bytes | None:
        return self.data.pop(key, None)


_CTX = PreviewContext(
    url="https://youtube.com/watch?v=abc", extractor_key="youtube", max_compatible_short_side=1080
)


def _store(fake: _FakeRedis, ttl: int = 600) -> RedisPreviewContextStore:
    redis: Any = fake  # duck-typed stand-in for redis.asyncio.Redis
    return RedisPreviewContextStore(redis=redis, ttl_seconds=ttl)


async def test_save_returns_short_callback_safe_token() -> None:
    fake = _FakeRedis()
    token = await _store(fake).save(_CTX)
    # 32-char hex + "dl:" prefix must fit Telegram's 64-byte limit.
    assert len(token) == 32
    assert token.isalnum()


async def test_roundtrip_save_get() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    token = await store.save(_CTX)
    assert await store.get(token) == _CTX


async def test_get_unknown_token_returns_none() -> None:
    fake = _FakeRedis()
    assert await _store(fake).get("deadbeef" * 4) is None


async def test_delete_removes_entry() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    token = await store.save(_CTX)
    await store.delete(token)
    assert await store.get(token) is None


async def test_delete_is_idempotent() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    await store.delete("nonexistent")  # must not raise


async def test_ttl_is_passed_to_redis() -> None:
    fake = _FakeRedis()
    await _store(fake, ttl=123).save(_CTX)
    assert fake.last_ttl == 123


async def test_tokens_are_unique() -> None:
    fake = _FakeRedis()
    store = _store(fake)
    tokens = {await store.save(_CTX) for _ in range(50)}
    assert len(tokens) == 50


async def test_unknown_short_side_roundtrips_as_none() -> None:
    store = _store(_FakeRedis())
    ctx = PreviewContext(
        url="https://x.com/v", extractor_key="twitter", max_compatible_short_side=None
    )
    assert await store.get(await store.save(ctx)) == ctx


async def test_pop_returns_context_once() -> None:
    store = _store(_FakeRedis())
    token = await store.save(_CTX)
    assert await store.pop(token) == _CTX
    assert await store.pop(token) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"https://youtube.com/watch?v=abc",  # bare URL written by the pre-11C-v2 deploy
        b'{"url": "https://x.y"}',  # missing fields
        b'{"url": 1, "extractor_key": "youtube", "max_compatible_short_side": null}',
        b'{"url": "https://x.y", "extractor_key": "youtube", "max_compatible_short_side": "1080"}',
    ],
)
async def test_unreadable_entry_reads_as_expired_and_is_logged(raw: bytes) -> None:
    # Guessing an extractor for a legacy entry would let a stale card skip
    # FormatPolicy; "expired" is the honest answer.
    fake = _FakeRedis()
    fake.data["umd:preview:" + "a" * 32] = raw
    store = _store(fake)

    with structlog.testing.capture_logs() as logs:
        assert await store.get("a" * 32) is None

    assert [e["event"] for e in logs] == ["preview_context_unreadable"]
    assert logs[0]["log_level"] == "warning"
