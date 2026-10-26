"""Redis implementation of PreviewContextStorePort.

Tokens are uuid4 hex (32 chars) — comfortably within Telegram's 64-byte
callback_data budget even with a "dl:" prefix, and unguessable, so one
user cannot trigger a download of another user's stored URL by forging
a callback (defense in depth; callbacks are also per-chat anyway).

TTL is enforced by Redis itself (SET ... EX), not by application code —
no cleanup job needed, expired entries just vanish.

Day 11C stage 4 adds ``pop`` on top of Redis GETDEL (server-side, one
round trip) — see the port docstring for why get+delete isn't good
enough for the confirm step.

Day 11C (v2): the value is a JSON-encoded PreviewContext instead of a
bare URL. An entry that doesn't decode — in practice only a bare-URL
entry written by the previous deploy, at most ``ttl_seconds`` old — is
reported as missing: the card shows the usual "preview expired" and the
user re-sends the link. Guessing the extractor for it instead would
let a stale card skip the FormatPolicy check this context exists for.
"""

from __future__ import annotations

import json
import uuid

from redis.asyncio import Redis

from src.domain.value_objects.preview_context import PreviewContext
from src.shared.logging import describe_error, get_logger

_KEY_PREFIX = "umd:preview:"

logger = get_logger(__name__)


def _encode(context: PreviewContext) -> str:
    return json.dumps(
        {
            "url": context.url,
            "extractor_key": context.extractor_key,
            "max_compatible_short_side": context.max_compatible_short_side,
        }
    )


def _decode(token: str, value: bytes | str | None) -> PreviewContext | None:
    if value is None:
        return None
    raw = value.decode("utf-8") if isinstance(value, bytes) else str(value)
    try:
        data = json.loads(raw)
        side = data["max_compatible_short_side"]
        if not isinstance(data["url"], str) or not isinstance(data["extractor_key"], str):
            raise TypeError("url/extractor_key must be strings")
        if side is not None and not isinstance(side, int):
            raise TypeError("max_compatible_short_side must be int or null")
        return PreviewContext(
            url=data["url"],
            extractor_key=data["extractor_key"],
            max_compatible_short_side=side,
        )
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("preview_context_unreadable", token=token, error=describe_error(exc))
        return None


class RedisPreviewContextStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def save(self, context: PreviewContext) -> str:
        token = uuid.uuid4().hex
        await self._redis.set(_KEY_PREFIX + token, _encode(context), ex=self._ttl_seconds)
        return token

    async def get(self, token: str) -> PreviewContext | None:
        return _decode(token, await self._redis.get(_KEY_PREFIX + token))

    async def delete(self, token: str) -> None:
        await self._redis.delete(_KEY_PREFIX + token)

    async def pop(self, token: str) -> PreviewContext | None:
        """GETDEL — atomic claim. Redis >= 6.2 (we run 7.x)."""
        return _decode(token, await self._redis.getdel(_KEY_PREFIX + token))
