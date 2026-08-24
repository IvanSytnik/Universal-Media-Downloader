"""Repository interface for DownloadRequest. Domain layer.

Not used yet (Day 2) — implementation added now because the ORM model
and migration are created now, and an unused-but-untested repository
would violate the "every module must have tests" rule once it exists.
Wired into a use case starting Day 5.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.domain.entities.download_request import DownloadRequest


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

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]: ...
