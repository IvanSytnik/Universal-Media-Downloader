"""Local disk implementation of StoragePort.

Each DownloadRequest gets its own subdirectory (named by request id),
so cleanup and per-request isolation are trivial — no risk of one
request's cleanup deleting another's in-flight file.

Disk guard (ops minimum, ADR 0005). Three layers, by how much disk each
one actually reclaims:

1. ``release`` — the use case removes a request's directory when the job
   ends, however it ends. Before this, a delivered 700 MB file stayed on
   disk until the cron's TTL.
2. ``available_bytes`` — the use case refuses to start a download when
   free space is below the configured floor.
3. ``cleanup_expired`` — the cron sweeps what a crashed job left behind.
   Age is the LAST ACTIVITY anywhere in the entry (newest mtime in the
   tree), not the directory's own mtime: a directory's mtime only moves
   when entries are added or renamed, so a ``.part`` growing for half an
   hour would look idle. The caller's threshold is at least the worker's
   ``job_timeout``, so nothing a live job is writing can be that quiet.

Open files are not a problem on Linux: unlinking one is legal and the
space comes back when the last handle closes. The danger is deleting a
LIVE download, which is what the activity age guards against. Removal
failures (permissions, a file vanishing under a concurrent ``release``)
are logged and never counted as removed.

All filesystem work runs in a thread: the worker's event loop also
drives progress updates, and a tree walk or a large unlink must not
stall them.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from uuid import UUID

from src.shared.logging import get_logger

logger = get_logger(__name__)


def _last_activity(entry: Path) -> float:
    """Newest mtime of ``entry`` and everything under it (symlinks are
    not followed). Entries that vanish mid-walk are ignored."""
    newest = entry.lstat().st_mtime
    if not entry.is_dir() or entry.is_symlink():
        return newest
    for root, dirs, files in os.walk(entry, followlinks=False):
        for name in (*dirs, *files):
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except FileNotFoundError:
                continue
    return newest


def _size_bytes(entry: Path) -> int:
    if not entry.is_dir() or entry.is_symlink():
        return entry.lstat().st_size
    total = 0
    for root, _dirs, files in os.walk(entry, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except FileNotFoundError:
                continue
    return total


def _remove(entry: Path) -> bool:
    """True only if ``entry`` is gone afterwards. Errors are logged per
    path, not swallowed into a false success."""

    def _on_error(_func: object, path: str, exc: BaseException) -> None:
        if not isinstance(exc, FileNotFoundError):
            logger.warning("storage_remove_failed", path=path, error=str(exc))

    try:
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, onexc=_on_error)
        else:
            entry.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("storage_remove_failed", path=str(entry), error=str(exc))
    return not os.path.lexists(entry)


class LocalFileStorage:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def temp_dir_for_request(self, request_id: UUID) -> Path:
        request_dir = self._base_dir / str(request_id)
        request_dir.mkdir(parents=True, exist_ok=True)
        return request_dir

    async def release(self, request_id: UUID) -> None:
        await asyncio.to_thread(self._release_sync, request_id)

    def _release_sync(self, request_id: UUID) -> None:
        request_dir = self._base_dir / str(request_id)
        if not os.path.lexists(request_dir):
            return
        if not _remove(request_dir):
            # The cron gets another go at it once it is old enough.
            logger.warning("storage_release_incomplete", request_id=str(request_id))

    async def available_bytes(self) -> int:
        return (await asyncio.to_thread(shutil.disk_usage, self._base_dir)).free

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        return await asyncio.to_thread(self._cleanup_expired_sync, max_age_seconds)

    def _cleanup_expired_sync(self, max_age_seconds: int) -> int:
        now = time.time()
        removed = 0
        for entry in self._base_dir.iterdir():
            try:
                age_seconds = now - _last_activity(entry)
                if age_seconds <= max_age_seconds:
                    continue
                size = _size_bytes(entry)
            except FileNotFoundError:
                continue  # released by a job between iterdir() and here
            if _remove(entry):
                removed += 1
                logger.info(
                    "storage_cleanup_removed",
                    path=str(entry),
                    age_seconds=int(age_seconds),
                    size_bytes=size,
                )
        return removed
