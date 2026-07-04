"""Task queue interface. Domain layer — no implementation here.

`enqueue_ping` (Day 3) was a smoke test. `enqueue_download` (Day 5) is
the real thing — it takes a DownloadRequest id, not raw parameters,
because the request is already persisted by the time it's enqueued
(see RequestDownloadUseCase); the worker loads full state from the DB
rather than trusting whatever was in the queue message.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class TaskQueue(Protocol):
    async def enqueue_ping(self, message: str) -> str:
        """Enqueue a ping job. Returns the job id."""
        ...

    async def enqueue_download(self, request_id: UUID) -> str:
        """Enqueue a download job for an already-persisted DownloadRequest.
        Returns the job id."""
        ...
