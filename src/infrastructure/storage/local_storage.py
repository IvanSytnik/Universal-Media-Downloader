"""Local disk implementation of StoragePort.

Each DownloadRequest gets its own subdirectory (named by request id),
so cleanup and per-request isolation are trivial — no risk of one
request's cleanup deleting another's in-flight file.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from uuid import UUID

from src.shared.logging import get_logger

logger = get_logger(__name__)


class LocalFileStorage:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def temp_dir_for_request(self, request_id: UUID) -> Path:
        request_dir = self._base_dir / str(request_id)
        request_dir.mkdir(parents=True, exist_ok=True)
        return request_dir

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        # Synchronous filesystem walk — fine here: this runs from a cron
        # job (see worker_settings.py), not on a latency-sensitive path,
        # and directory counts are small (one per recent request).
        now = time.time()
        removed = 0

        for entry in self._base_dir.iterdir():
            if not entry.is_dir():
                continue
            age_seconds = now - entry.stat().st_mtime
            if age_seconds > max_age_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
                logger.info(
                    "storage_cleanup_removed", path=str(entry), age_seconds=int(age_seconds)
                )

        return removed
