"""TriggerPingJobUseCase — the first use case that touches the task queue.

Same pattern as RegisterUserUseCase: depends only on the domain
interface (`TaskQueue`), never on arq directly. Testable with a fake,
no Redis required (see tests/unit/test_trigger_ping_job_use_case.py).
"""

from __future__ import annotations

from src.domain.interfaces.task_queue import TaskQueue


class TriggerPingJobUseCase:
    def __init__(self, task_queue: TaskQueue) -> None:
        self._task_queue = task_queue

    async def execute(self, message: str) -> str:
        return await self._task_queue.enqueue_ping(message)
