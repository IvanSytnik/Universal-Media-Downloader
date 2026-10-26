"""Repository interface for DownloadRequest. Domain layer.

Not used yet (Day 2) — implementation added now because the ORM model
and migration are created now, and an unused-but-untested repository
would violate the "every module must have tests" rule once it exists.
Wired into a use case starting Day 5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from src.domain.entities.download_request import DownloadRequest
from src.domain.value_objects.stale_request import StaleRequest


class DownloadRequestRepository(Protocol):
    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None: ...

    async def create(self, download_request: DownloadRequest) -> DownloadRequest: ...

    async def update(self, download_request: DownloadRequest) -> None: ...

    async def mark_failed_by_id(self, request_id: UUID) -> None:
        """Fail a request by id, without needing it as an entity.

        Needed because the one case that must mark a request failed is
        precisely the case where the entity can't be built: a row whose
        stored status is unreadable (CorruptedRecordError). ``update``
        takes a DownloadRequest and so is unusable there.
        """
        ...

    async def claim_for_processing(self, request_id: UUID) -> bool:
        """Atomically move the request to PROCESSING if it is still
        active (PENDING, or PROCESSING — an arq retry after a worker
        crash), refreshing its last-update time. False when it is not:
        finished, reaped, or gone. The caller must then not process it.

        A compare-and-set, not read-then-write: it is what keeps a job
        and the reaper from overwriting each other's transition.
        """
        ...

    async def fail_stale(self, updated_before: datetime, limit: int) -> list[StaleRequest]:
        """Move up to ``limit`` active requests last updated strictly
        before ``updated_before`` to FAILED, oldest first, and return
        them. Each row is transitioned at most once: a second call (or a
        concurrent reaper) does not see it again.
        """
        ...

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]: ...
