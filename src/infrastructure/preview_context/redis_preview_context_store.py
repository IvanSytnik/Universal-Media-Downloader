"""Redis implementation of PreviewContextStorePort.

Tokens are uuid4 hex (32 chars) — comfortably within Telegram's 64-byte
callback_data budget even with a "dl:" prefix, and unguessable, so one
user cannot trigger a download of another user's stored URL by forging
a callback (defense in depth; callbacks are also per-chat anyway).

TTL is enforced by Redis itself (SET ... EX), not by application code —
no cleanup job needed, expired entries just vanish.
"""

from __future__ import annotations

import uuid

from redis.asyncio import Redis

_KEY_PREFIX = "umd:preview:"


class RedisPreviewContextStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def save(self, url: str) -> str:
        token = uuid.uuid4().hex
        await self._redis.set(_KEY_PREFIX + token, url, ex=self._ttl_seconds)
        return token

    async def get(self, token: str) -> str | None:
        value = await self._redis.get(_KEY_PREFIX + token)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def delete(self, token: str) -> None:
        await self._redis.delete(_KEY_PREFIX + token)
