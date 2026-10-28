"""StoragePort — domain interface for where downloaded files live
temporarily before being sent to the user, and how they get cleaned up.

Day 5 implementation is local disk (docs/architecture.md, Large-file delivery —
object storage is not pulled in early "just in case").
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

    async def release(self, request_id: UUID) -> None:
        """Removes the request's directory and everything in it, if it
        exists. Called when the job ends, however it ends. Never raises:
        a removal that fails is logged and left to ``cleanup_expired``.
        """
        ...

    async def available_bytes(self) -> int:
        """Free space, in bytes, where request directories live."""
        ...

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        """Deletes temp entries with no activity (newest mtime anywhere
        inside) for more than `max_age_seconds` — what a crashed job left
        behind. Returns the number of entries actually removed. Called
        periodically by a cron job (see worker_settings.py), not by
        request handlers.
        """
        ...
