"""DownloadRequest domain entity.

Represents a single download attempt. Existed since Day 2 as a
persisted record; Day 5 adds the state-transition methods, since this
is the first day it's actually driven through its lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.domain.value_objects.enums import DownloadStatus, MediaType


@dataclass(slots=True)
class DownloadRequest:
    id: UUID
    user_id: UUID
    source_url: str
    media_type: MediaType = MediaType.UNKNOWN
    status: DownloadStatus = DownloadStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @classmethod
    def create(cls, user_id: UUID, source_url: str) -> DownloadRequest:
        return cls(id=uuid4(), user_id=user_id, source_url=source_url)

    def mark_processing(self) -> None:
        self.status = DownloadStatus.PROCESSING

    def mark_done(self) -> None:
        self.status = DownloadStatus.DONE
        self.completed_at = datetime.now(UTC)

    def mark_failed(self) -> None:
        self.status = DownloadStatus.FAILED
        self.completed_at = datetime.now(UTC)
