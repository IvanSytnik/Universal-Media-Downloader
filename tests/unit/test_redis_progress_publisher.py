"""RedisProgressPublisher — capture-args test (not a bare mock, lesson
11A.1): a fake Redis client records what PUBLISH was actually called
with, and the test asserts on the decoded JSON + channel name.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from src.domain.value_objects.download_progress import DownloadProgress
from src.infrastructure.progress.redis_progress_publisher import RedisProgressPublisher


class _CapturingRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


@pytest.mark.asyncio
async def test_publish_sends_correct_channel_and_json_payload() -> None:
    redis = _CapturingRedis()
    publisher = RedisProgressPublisher(redis)  # type: ignore[arg-type]
    request_id = uuid4()
    progress = DownloadProgress(
        percent=33.3, downloaded_bytes=333, total_bytes=1000, speed=100.0, eta=7
    )

    await publisher.publish(
        request_id, chat_id=555, message_id=42, language="ru", progress=progress
    )

    assert len(redis.published) == 1
    channel, raw_message = redis.published[0]
    assert channel == f"umd:progress:{request_id}"

    payload = json.loads(raw_message)
    assert payload == {
        "percent": 33.3,
        "downloaded_bytes": 333,
        "total_bytes": 1000,
        "speed": 100.0,
        "eta": 7,
        "phase": "downloading",
        "chat_id": 555,
        "message_id": 42,
        "language": "ru",
    }


@pytest.mark.asyncio
async def test_publish_with_none_language_and_percent() -> None:
    redis = _CapturingRedis()
    publisher = RedisProgressPublisher(redis)  # type: ignore[arg-type]
    request_id = uuid4()
    progress = DownloadProgress(
        percent=None, downloaded_bytes=100, total_bytes=None, speed=None, eta=None
    )

    await publisher.publish(request_id, chat_id=1, message_id=2, language=None, progress=progress)

    _, raw_message = redis.published[0]
    payload = json.loads(raw_message)
    assert payload["percent"] is None
    assert payload["language"] is None
