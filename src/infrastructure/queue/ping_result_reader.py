"""Redis-backed ``PingResultReader`` — reads what ``ping_job`` recorded."""

from __future__ import annotations

import json

from redis.asyncio import Redis

from src.domain.value_objects.ping_result import PingResult
from src.infrastructure.queue.jobs import LAST_PING_REDIS_KEY


class RedisPingResultReader:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get_last(self) -> PingResult | None:
        raw = await self._redis.get(LAST_PING_REDIS_KEY)
        if raw is None:
            return None
        data = json.loads(raw)
        return PingResult(message=data["message"], processed_at=data["processed_at"])
