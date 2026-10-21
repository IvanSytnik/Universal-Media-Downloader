"""RedisPingResultReader reads back exactly what ping_job writes."""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.value_objects.ping_result import PingResult
from src.infrastructure.queue.jobs import ping_job
from src.infrastructure.queue.ping_result_reader import RedisPingResultReader


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    async def get(self, key: str) -> Any:
        return self._data.get(key)


@pytest.mark.asyncio
async def test_returns_none_before_any_ping() -> None:
    reader = RedisPingResultReader(_FakeRedis())  # type: ignore[arg-type]
    assert await reader.get_last() is None


@pytest.mark.asyncio
async def test_round_trips_the_ping_job_result() -> None:
    redis = _FakeRedis()
    written = await ping_job({"redis": redis}, "hello")

    result = await RedisPingResultReader(redis).get_last()  # type: ignore[arg-type]

    assert result == PingResult(message="hello", processed_at=written["processed_at"])
