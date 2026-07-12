"""Job functions executed by the arq worker.

`ping_job` (Day 3) is a smoke test. `download_job` (Day 5) is the real
thing: loads a DownloadRequest by id and drives it through
ProcessDownloadUseCase using dependencies stashed in `ctx` at worker
startup (see worker_settings.py) — a fresh DB session per job, but a
shared downloader/storage/notifier/error_localizer across the worker's
lifetime.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.shared.logging import get_logger

logger = get_logger(__name__)

LAST_PING_REDIS_KEY = "worker:last_ping"


async def ping_job(ctx: dict[str, Any], message: str) -> dict[str, str]:
    processed_at = datetime.now(UTC).isoformat()
    result = {"message": message, "processed_at": processed_at}

    redis = ctx["redis"]
    await redis.set(LAST_PING_REDIS_KEY, json.dumps(result))

    logger.info("ping_job_processed", message=message, processed_at=processed_at)
    return result


async def download_job(ctx: dict[str, Any], request_id: str) -> None:
    session_factory = ctx["session_factory"]

    async with session_scope(session_factory) as session:
        use_case = ProcessDownloadUseCase(
            download_request_repository=SqlAlchemyDownloadRequestRepository(session),
            user_repository=SqlAlchemyUserRepository(session),
            downloader=ctx["downloader"],
            storage=ctx["storage"],
            notifier=ctx["notifier"],
            error_localizer=ctx["error_localizer"],
            max_deliverable_file_size_bytes=ctx["max_deliverable_file_size_bytes"],
            download_timeout_seconds=ctx["download_timeout_seconds"],
        )
        await use_case.execute(UUID(request_id))


async def cleanup_expired_downloads_job(ctx: dict[str, Any]) -> None:
    """Runs on a cron schedule (see worker_settings.py) — not triggered
    by any single download, so old temp files get removed even if the
    server never restarts."""
    storage = ctx["storage"]
    removed = await storage.cleanup_expired(max_age_seconds=3600)
    if removed:
        logger.info("cleanup_expired_downloads", removed_count=removed)
