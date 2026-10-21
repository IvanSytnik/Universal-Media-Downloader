"""Read side of the worker ping smoke test. Domain layer — no implementation here.

The worker's ``ping_job`` records its result; the bot reads it back for
``/worker_status``. The storage key and serialization are infrastructure
details, so the bot only sees this port.
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.ping_result import PingResult


class PingResultReader(Protocol):
    async def get_last(self) -> PingResult | None:
        """The last recorded ping result, or ``None`` if none exists yet."""
        ...
