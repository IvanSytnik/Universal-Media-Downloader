"""TriggerPingJobUseCase tests using an in-memory fake — no Redis at all."""

from __future__ import annotations

import pytest

from src.application.use_cases.trigger_ping_job import TriggerPingJobUseCase


class FakeTaskQueue:
    def __init__(self) -> None:
        self.enqueued_messages: list[str] = []

    async def enqueue_ping(self, message: str) -> str:
        self.enqueued_messages.append(message)
        return f"fake-job-{len(self.enqueued_messages)}"


@pytest.mark.asyncio
async def test_trigger_ping_job_returns_job_id() -> None:
    queue = FakeTaskQueue()
    use_case = TriggerPingJobUseCase(queue)

    job_id = await use_case.execute("hello")

    assert job_id == "fake-job-1"
    assert queue.enqueued_messages == ["hello"]


@pytest.mark.asyncio
async def test_trigger_ping_job_passes_message_through_unchanged() -> None:
    queue = FakeTaskQueue()
    use_case = TriggerPingJobUseCase(queue)

    await use_case.execute("custom message with spaces")

    assert queue.enqueued_messages == ["custom message with spaces"]
