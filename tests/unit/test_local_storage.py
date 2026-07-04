"""LocalFileStorage tests — real filesystem (tmp_path fixture), no mocks."""

from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest

from src.infrastructure.storage.local_storage import LocalFileStorage


def test_temp_dir_for_request_creates_directory(tmp_path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    request_id = uuid4()

    result = storage.temp_dir_for_request(request_id)

    assert result.exists()
    assert result.is_dir()
    assert result == tmp_path / str(request_id)


@pytest.mark.asyncio
async def test_cleanup_expired_removes_old_directories(tmp_path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)

    old_dir = storage.temp_dir_for_request(uuid4())
    (old_dir / "video.mp4").write_bytes(b"fake content")
    # Backdate mtime to simulate an old directory without sleeping in the test.
    old_time = time.time() - 7200
    os.utime(old_dir, (old_time, old_time))

    fresh_dir = storage.temp_dir_for_request(uuid4())
    (fresh_dir / "video.mp4").write_bytes(b"fake content")

    removed = await storage.cleanup_expired(max_age_seconds=3600)

    assert removed == 1
    assert not old_dir.exists()
    assert fresh_dir.exists()


@pytest.mark.asyncio
async def test_cleanup_expired_with_nothing_to_remove(tmp_path) -> None:
    storage = LocalFileStorage(base_dir=tmp_path)
    storage.temp_dir_for_request(uuid4())

    removed = await storage.cleanup_expired(max_age_seconds=3600)

    assert removed == 0
