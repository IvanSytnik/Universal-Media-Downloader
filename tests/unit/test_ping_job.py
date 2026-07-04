"""ping_job tests using a fake Redis client — no real Redis connection.

Mirrors the pattern used for repository tests (fast, self-contained).
Real end-to-end verification (bot → Redis → worker → Redis → bot) is
done via `docker compose up` + /worker_ping + /worker_status, same as
every other infra-touching piece in this project so far.
"""

from __future__ import annotations

import json

import pytest

from src.infrastructure.queue.jobs import LAST_PING_REDIS_KEY, ping_job


class FakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}

    async def set(self, key: str, value: str) -> None:
        self.storage[key] = value


@pytest.mark.asyncio
async def test_ping_job_writes_result_to_redis() -> None:
    fake_redis = FakeRedis()
    ctx = {"redis": fake_redis}

    result = await ping_job(ctx, "test message")

    assert result["message"] == "test message"
    assert "processed_at" in result

    stored = json.loads(fake_redis.storage[LAST_PING_REDIS_KEY])
    assert stored["message"] == "test message"
    assert stored["processed_at"] == result["processed_at"]
