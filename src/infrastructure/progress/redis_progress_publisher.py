"""RedisProgressPublisher — infra implementation of ProgressPublisherPort.

Day 11B. PUBLISHes a JSON payload to ``umd:progress:<request_id>``. The
payload bundles DownloadProgress's own fields with the routing/rendering
extras (chat_id, message_id, language) that ProgressPublisherPort takes
as separate parameters (see that port's docstring for why this isn't a
Dependency Rule violation) — the listener needs all of it in one message
to avoid a DB round trip per update (TASK_Day11B.md payload decision).

Uses whatever ``Redis``-compatible client is injected. The worker doesn't
open a dedicated connection for this: ``ctx["redis"]`` (arq's own
``ArqRedis``, a ``redis.asyncio.Redis`` subclass) already exists for the
lifetime of the worker process and supports PUBLISH — see
worker_settings.py.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import UUID

from src.domain.value_objects.download_progress import DownloadProgress

if TYPE_CHECKING:
    from redis.asyncio import Redis

_CHANNEL_PREFIX = "umd:progress:"


class RedisProgressPublisher:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(
        self,
        request_id: UUID,
        chat_id: int,
        message_id: int,
        language: str | None,
        progress: DownloadProgress,
    ) -> None:
        payload = {
            **asdict(progress),
            "chat_id": chat_id,
            "message_id": message_id,
            "language": language,
        }
        await self._redis.publish(f"{_CHANNEL_PREFIX}{request_id}", json.dumps(payload))
