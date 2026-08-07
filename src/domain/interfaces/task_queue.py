"""Task queue interface. Domain layer — no implementation here.

`enqueue_ping` (Day 3) was a smoke test. `enqueue_download` (Day 5) is
the real thing — it takes a DownloadRequest id, not raw parameters,
because the request is already persisted by the time it's enqueued
(see RequestDownloadUseCase); the worker loads full state from the DB
rather than trusting whatever was in the queue message.

Day 11B adds ``chat_id``/``message_id``: the coordinates of the message
progress updates should edit. These are a transport/delivery detail, not
part of the persisted request (contrast with ``format_kind``, Day 11A) —
they ride in the job payload only, required with no default so a caller
can't silently enqueue a download with nowhere for progress to go.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class TaskQueue(Protocol):
    async def enqueue_ping(self, message: str) -> str:
        """Enqueue a ping job. Returns the job id."""
        ...

    async def enqueue_download(self, request_id: UUID, chat_id: int, message_id: int) -> str:
        """Enqueue a download job for an already-persisted DownloadRequest.

        ``chat_id``/``message_id`` identify the message the worker's
        progress updates (and eventual success/failure notification's
        preceding edits) should target. Returns the job id."""
        ...
