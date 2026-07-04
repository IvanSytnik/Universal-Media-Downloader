"""arq implementation of TaskQueue (domain interface). Enqueue side — used
by the bot process to push jobs. The worker process consumes them via
WorkerSettings (see worker_settings.py), not via this class.
"""

from __future__ import annotations

from uuid import UUID

from arq import ArqRedis


class ArqTaskQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_ping(self, message: str) -> str:
        job = await self._pool.enqueue_job("ping_job", message)
        if job is None:
            # arq returns None only if a job with the same explicit `_job_id`
            # already exists and hasn't completed — we don't set one here,
            # so this branch is defensive, not expected in practice.
            raise RuntimeError("Failed to enqueue ping job (duplicate job_id?)")
        return job.job_id

    async def enqueue_download(self, request_id: UUID) -> str:
        job = await self._pool.enqueue_job("download_job", str(request_id))
        if job is None:
            raise RuntimeError("Failed to enqueue download job (duplicate job_id?)")
        return job.job_id
