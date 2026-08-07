"""ArqTaskQueue tests using a fake pool — checks the adapter logic itself
(job_id extraction, the defensive None-check), not arq/Redis behavior.

Day 11B: `enqueue_download` gained `chat_id`/`message_id` — no coverage
existed for this method at all before, so it's added here alongside the
new arguments (capturing exactly what enqueue_job was called with,
lesson 11A.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from src.infrastructure.queue.arq_task_queue import ArqTaskQueue


@dataclass
class FakeJob:
    job_id: str


class FakePool:
    def __init__(self, job_id: str | None = "job-abc123") -> None:
        self._job_id = job_id
        self.enqueued: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue_job(self, function: str, *args: object) -> FakeJob | None:
        self.enqueued.append((function, args))
        if self._job_id is None:
            return None
        return FakeJob(job_id=self._job_id)


@pytest.mark.asyncio
async def test_enqueue_ping_returns_job_id() -> None:
    pool = FakePool(job_id="job-abc123")
    queue = ArqTaskQueue(pool)  # type: ignore[arg-type]  # FakePool duck-types ArqRedis for this call

    job_id = await queue.enqueue_ping("hello")

    assert job_id == "job-abc123"
    assert pool.enqueued == [("ping_job", ("hello",))]


@pytest.mark.asyncio
async def test_enqueue_ping_raises_when_pool_returns_none() -> None:
    pool = FakePool(job_id=None)
    queue = ArqTaskQueue(pool)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await queue.enqueue_ping("hello")


@pytest.mark.asyncio
async def test_enqueue_download_passes_request_id_chat_id_message_id() -> None:
    pool = FakePool(job_id="job-download-1")
    queue = ArqTaskQueue(pool)  # type: ignore[arg-type]
    request_id = uuid4()

    job_id = await queue.enqueue_download(request_id, chat_id=555, message_id=42)

    assert job_id == "job-download-1"
    assert pool.enqueued == [("download_job", (str(request_id), 555, 42))]


@pytest.mark.asyncio
async def test_enqueue_download_raises_when_pool_returns_none() -> None:
    pool = FakePool(job_id=None)
    queue = ArqTaskQueue(pool)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError):
        await queue.enqueue_download(uuid4(), chat_id=1, message_id=2)
