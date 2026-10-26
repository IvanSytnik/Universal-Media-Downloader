"""Job functions executed by the arq worker.

`ping_job` (Day 3) is a smoke test. `download_job` (Day 5) is the real
thing: loads a DownloadRequest by id and drives it through
ProcessDownloadUseCase using dependencies stashed in `ctx` at worker
startup (see worker_settings.py) — a fresh DB session per job, but a
shared downloader/storage/notifier/error_localizer across the worker's
lifetime.

Day 11B: `download_job` gains `chat_id`/`message_id` — the coordinates
of the message to edit with progress, threaded in from
RequestDownloadUseCase's enqueue call (see TaskQueue docstring).

Stale-request reaper (ADR 0004): `download_job` no longer wraps the use
case in one transaction — its repositories commit per call
(transactional.py), so PROCESSING is visible and durable the moment the
job claims the request. `reap_stale_requests_job` runs on cron.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.application.use_cases.reap_stale_requests import ReapStaleRequestsUseCase
from src.infrastructure.database.repositories.transactional import (
    TransactionalDownloadRequestRepository,
    TransactionalUserRepository,
)
from src.shared.logging import bind_log_context, clear_log_context, get_logger

logger = get_logger(__name__)

LAST_PING_REDIS_KEY = "worker:last_ping"

# Rows per reaper tick. Far above anything a healthy beta produces in 5
# minutes; a backlog (first tick after an outage) drains over a few ticks
# instead of one burst of Telegram messages.
REAPER_BATCH_SIZE = 100


async def ping_job(ctx: dict[str, Any], message: str) -> dict[str, str]:
    processed_at = datetime.now(UTC).isoformat()
    result = {"message": message, "processed_at": processed_at}

    redis = ctx["redis"]
    await redis.set(LAST_PING_REDIS_KEY, json.dumps(result))

    logger.info("ping_job_processed", message=message, processed_at=processed_at)
    return result


async def download_job(ctx: dict[str, Any], request_id: str, chat_id: int, message_id: int) -> None:
    clear_log_context()
    bind_log_context(job="download_job", request_id=request_id)
    session_factory = ctx["session_factory"]
    use_case = ProcessDownloadUseCase(
        download_request_repository=TransactionalDownloadRequestRepository(session_factory),
        user_repository=TransactionalUserRepository(session_factory),
        downloader=ctx["downloader"],
        storage=ctx["storage"],
        notifier=ctx["notifier"],
        error_localizer=ctx["error_localizer"],
        progress_publisher=ctx["progress_publisher"],
        max_deliverable_file_size_bytes=ctx["max_deliverable_file_size_bytes"],
        download_timeout_seconds=ctx["download_timeout_seconds"],
        min_free_disk_bytes=ctx["download_min_free_disk_bytes"],
    )
    await use_case.execute(UUID(request_id), chat_id, message_id)


async def reap_stale_requests_job(ctx: dict[str, Any]) -> int:
    """Cron (see worker_settings.py). Returns how many requests it failed."""
    clear_log_context()
    bind_log_context(job="reap_stale_requests_job")
    session_factory = ctx["session_factory"]
    use_case = ReapStaleRequestsUseCase(
        download_request_repository=TransactionalDownloadRequestRepository(session_factory),
        user_repository=TransactionalUserRepository(session_factory),
        notifier=ctx["notifier"],
        error_localizer=ctx["error_localizer"],
        stale_after=ctx["stale_request_after"],
        batch_size=REAPER_BATCH_SIZE,
        clock=lambda: datetime.now(UTC),
    )
    reaped = await use_case.execute()
    if reaped:
        logger.info("stale_requests_reaped", count=len(reaped))
    return len(reaped)


async def cleanup_expired_downloads_job(ctx: dict[str, Any]) -> None:
    """Runs on a cron schedule (see worker_settings.py) — not triggered
    by any single download, so old temp files get removed even if the
    server never restarts.

    Disk guard (ADR 0005): jobs release their own directories now, so
    this only sweeps what a crashed job left. The age threshold is the
    reaper's (job_timeout + grace): no live job goes that long without
    touching its files. Low free space is logged here too — the per-job
    check refuses downloads, this line is what an operator sees.
    """
    clear_log_context()
    bind_log_context(job="cleanup_expired_downloads_job")
    storage = ctx["storage"]
    max_age = int(ctx["stale_request_after"].total_seconds())
    removed = await storage.cleanup_expired(max_age_seconds=max_age)
    if removed:
        logger.info("cleanup_expired_downloads", removed_count=removed)

    available = await storage.available_bytes()
    if available < ctx["download_min_free_disk_bytes"]:
        logger.warning(
            "storage_low_disk_space",
            available_bytes=available,
            min_free_bytes=ctx["download_min_free_disk_bytes"],
        )
