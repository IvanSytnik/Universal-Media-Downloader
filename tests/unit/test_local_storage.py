"""LocalFileStorage tests — real filesystem (tmp_path fixture), no mocks
except where a failure has to be forced.

Disk guard (ADR 0005): age is the newest mtime anywhere in an entry, so
most tests backdate whole trees with ``_age``; the live-download case
backdates everything but the growing ``.part``.
"""

from __future__ import annotations

import os
import sys
import time
from collections import namedtuple
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import structlog

from src.infrastructure.storage import local_storage
from src.infrastructure.storage.local_storage import LocalFileStorage

_HOUR = 3600


def _age(path: Path, seconds: float) -> None:
    """Backdate ``path`` and everything under it by ``seconds``."""
    stamp = time.time() - seconds
    for root, dirs, files in os.walk(path):
        for name in (*dirs, *files):
            os.utime(os.path.join(root, name), (stamp, stamp), follow_symlinks=False)
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _request_dir(storage: LocalFileStorage, *files: str) -> Path:
    request_dir = storage.temp_dir_for_request(uuid4())
    for name in files:
        target = request_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 10)
    return request_dir


def test_temp_dir_for_request_creates_directory(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    request_id = uuid4()

    result = storage.temp_dir_for_request(request_id)

    assert result.exists()
    assert result.is_dir()
    assert result == tmp_path / str(request_id)


# --- cleanup_expired ---------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_removes_idle_trees_and_keeps_fresh_ones(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    old_dir = _request_dir(storage, "video.mp4", "video.f137.mp4.part")
    _age(old_dir, 2 * _HOUR)
    fresh_dir = _request_dir(storage, "video.mp4")

    with structlog.testing.capture_logs() as logs:
        removed = await storage.cleanup_expired(max_age_seconds=_HOUR)

    assert removed == 1
    assert not old_dir.exists()
    assert fresh_dir.exists()
    entry = next(e for e in logs if e["event"] == "storage_cleanup_removed")
    assert entry["path"] == str(old_dir)
    assert entry["size_bytes"] == 20


@pytest.mark.asyncio
async def test_growing_part_file_keeps_an_old_directory_alive(tmp_path: Path) -> None:
    """The live-download case: yt-dlp created the directory long ago and
    has been appending to one ``.part`` since — the directory's own mtime
    never moved."""
    storage = LocalFileStorage(base_dir=tmp_path)
    live_dir = _request_dir(storage, "video.f137.mp4.part", "video.f140.m4a")
    _age(live_dir, 2 * _HOUR)
    with (live_dir / "video.f137.mp4.part").open("ab") as part:
        part.write(b"more")  # mtime = now; the directory's mtime stays old

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 0
    assert live_dir.exists()


@pytest.mark.asyncio
async def test_activity_deep_in_the_tree_counts(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    request_dir = _request_dir(storage, "a/b/c/fragment.ts")
    _age(request_dir, 2 * _HOUR)
    os.utime(request_dir / "a/b/c/fragment.ts")

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 0


@pytest.mark.asyncio
async def test_age_boundary_is_strictly_greater(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    at_limit = _request_dir(storage, "f")
    over_limit = _request_dir(storage, "f")
    now = time.time()
    _age(at_limit, 0)
    _age(over_limit, 0)
    for path, mtime in ((at_limit, now - _HOUR), (over_limit, now - _HOUR - 1)):
        for target in (path, path / "f"):
            os.utime(target, (mtime, mtime))
    monkeypatch.setattr(local_storage.time, "time", lambda: now)

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 1
    assert at_limit.exists()
    assert not over_limit.exists()


@pytest.mark.asyncio
async def test_stray_files_at_the_top_level_are_swept_too(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    stray = tmp_path / "orphan.mp4.part"
    stray.write_bytes(b"x")
    _age(stray, 2 * _HOUR)
    fresh_stray = tmp_path / "fresh.part"
    fresh_stray.write_bytes(b"x")

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 1
    assert not stray.exists()
    assert fresh_stray.exists()


@pytest.mark.asyncio
async def test_symlinks_are_removed_not_followed(tmp_path: Path) -> None:
    base = tmp_path / "downloads"
    outside = tmp_path / "precious.bin"
    outside.write_bytes(b"keep me")
    storage = LocalFileStorage(base_dir=base)
    request_dir = _request_dir(storage, "video.mp4")
    (request_dir / "link").symlink_to(outside)
    _age(request_dir, 2 * _HOUR)
    os.utime(outside)  # the target is fresh — it must not keep the dir alive

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 1
    assert not request_dir.exists()
    assert outside.read_bytes() == b"keep me"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX unlink semantics")
@pytest.mark.asyncio
async def test_file_held_open_is_removed_and_the_handle_keeps_working(tmp_path: Path) -> None:
    """An open file is not a 'lock' on POSIX: unlinking it is legal and
    the space comes back when the last handle closes."""
    storage = LocalFileStorage(base_dir=tmp_path)
    request_dir = _request_dir(storage)
    held = (request_dir / "video.mp4").open("w+b")
    try:
        held.write(b"still readable")
        held.flush()
        _age(request_dir, 2 * _HOUR)

        assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 1
        assert not request_dir.exists()
        held.seek(0)
        assert held.read() == b"still readable"
    finally:
        held.close()


@pytest.mark.asyncio
async def test_failed_removal_is_logged_and_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    stuck = _request_dir(storage, "video.mp4")
    _age(stuck, 2 * _HOUR)

    def _rmtree_denied(path: Any, onexc: Any) -> None:
        onexc(os.unlink, str(Path(path) / "video.mp4"), PermissionError("Permission denied"))

    monkeypatch.setattr(local_storage.shutil, "rmtree", _rmtree_denied)

    with structlog.testing.capture_logs() as logs:
        removed = await storage.cleanup_expired(max_age_seconds=_HOUR)

    assert removed == 0
    assert stuck.exists()
    failure = next(e for e in logs if e["event"] == "storage_remove_failed")
    assert "Permission denied" in failure["error"]
    assert not [e for e in logs if e["event"] == "storage_cleanup_removed"]


@pytest.mark.asyncio
async def test_entry_released_mid_sweep_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    vanishing = _request_dir(storage, "f")
    old = _request_dir(storage, "f")
    _age(vanishing, 2 * _HOUR)
    _age(old, 2 * _HOUR)
    real = local_storage._last_activity

    def _racy(entry: Path) -> float:
        if entry == vanishing:
            raise FileNotFoundError(entry)  # a job's release() won the race
        return real(entry)

    monkeypatch.setattr(local_storage, "_last_activity", _racy)

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 1
    assert not old.exists()


@pytest.mark.asyncio
async def test_cleanup_with_nothing_to_remove(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    storage.temp_dir_for_request(uuid4())

    assert await storage.cleanup_expired(max_age_seconds=_HOUR) == 0


# --- release / available_bytes ---------------------------------------------


@pytest.mark.asyncio
async def test_release_removes_the_request_directory_only(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    request_id = uuid4()
    mine = storage.temp_dir_for_request(request_id)
    (mine / "video.mp4").write_bytes(b"x")
    (mine / "video.f137.mp4.part").write_bytes(b"x")
    other = _request_dir(storage, "video.mp4")

    await storage.release(request_id)

    assert not mine.exists()
    assert other.exists()


@pytest.mark.asyncio
async def test_release_is_idempotent(tmp_path: Path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    request_id = uuid4()
    storage.temp_dir_for_request(request_id)

    await storage.release(request_id)
    await storage.release(request_id)  # already gone — no error
    await storage.release(uuid4())  # never existed — no error


@pytest.mark.asyncio
async def test_release_failure_is_logged_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    request_id = uuid4()
    storage.temp_dir_for_request(request_id)

    def _rmtree_denied(path: Any, onexc: Any) -> None:
        onexc(os.rmdir, str(path), OSError(16, "Device or resource busy"))

    monkeypatch.setattr(local_storage.shutil, "rmtree", _rmtree_denied)

    with structlog.testing.capture_logs() as logs:
        await storage.release(request_id)

    events = [e["event"] for e in logs]
    assert "storage_remove_failed" in events
    assert "storage_release_incomplete" in events


@pytest.mark.asyncio
async def test_available_bytes_reads_the_download_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = namedtuple("usage", "total used free")
    seen: list[Path] = []

    def _disk_usage(path: Path) -> Any:
        seen.append(path)
        return usage(100, 60, 40)

    storage = LocalFileStorage(base_dir=tmp_path)
    monkeypatch.setattr(local_storage.shutil, "disk_usage", _disk_usage)

    assert await storage.available_bytes() == 40
    assert seen == [tmp_path]
