"""The storage cron job: threshold taken from the reaper's, and the
low-disk warning an operator sees."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
import structlog

from src.infrastructure.queue.jobs import cleanup_expired_downloads_job


class _Storage:
    def __init__(self, available: int) -> None:
        self._available = available
        self.max_ages: list[int] = []

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        self.max_ages.append(max_age_seconds)
        return 2

    async def available_bytes(self) -> int:
        return self._available


def _ctx(storage: _Storage) -> dict[str, Any]:
    return {
        "storage": storage,
        "stale_request_after": timedelta(seconds=2400),
        "download_min_free_disk_bytes": 1000,
    }


@pytest.mark.asyncio
async def test_sweeps_with_the_reaper_threshold() -> None:
    storage = _Storage(available=10**9)

    with structlog.testing.capture_logs() as logs:
        await cleanup_expired_downloads_job(_ctx(storage))

    assert storage.max_ages == [2400]
    assert [e["removed_count"] for e in logs if e["event"] == "cleanup_expired_downloads"] == [2]
    assert not [e for e in logs if e["event"] == "storage_low_disk_space"]


@pytest.mark.asyncio
async def test_warns_when_free_space_is_below_the_floor() -> None:
    with structlog.testing.capture_logs() as logs:
        await cleanup_expired_downloads_job(_ctx(_Storage(available=999)))

    warning = next(e for e in logs if e["event"] == "storage_low_disk_space")
    assert warning["log_level"] == "warning"
    assert warning["available_bytes"] == 999
    assert warning["min_free_bytes"] == 1000
