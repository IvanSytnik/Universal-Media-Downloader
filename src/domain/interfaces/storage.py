"""StoragePort — domain interface for where downloaded files live
temporarily before being sent to the user, and how they get cleaned up.

Day 5 implementation is local disk (see PROJECT_SPEC §6.2 — S3/MinIO is
explicitly Phase 7, not pulled in early "just in case").
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID


class StoragePort(Protocol):
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        """Returns (and creates if needed) a directory scoped to one
        DownloadRequest. Callers download into this directory; nothing
        else should share it."""
        ...

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """Deletes temp directories older than `max_age_seconds`.
        Returns the number of directories removed. Called periodically
        by a cron job (see worker_settings.py), not by request handlers.
        """
        ...
