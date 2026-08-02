"""DownloadRequest domain entity.

Represents a single download attempt. Existed since Day 2 as a
persisted record; Day 5 adds the state-transition methods, since this
is the first day it's actually driven through its lifecycle.

Day 11A adds ``format_kind``: whether the user asked for the video or an
mp3. It lives on the *entity* (and therefore in the DB) rather than
riding in the queue payload, because the worker rebuilds the entire
request from the database by id — the queue message carries only the
request id (see TaskQueue docstring). Anything the worker needs to know
about WHAT to download has to be persisted, or the worker can't see it.
It also belongs here semantically: "the user requested the audio of this
URL" is a property of the request, not a transport detail. (Contrast
with Day 11B's progress message coordinates, which ARE a transport
detail and correctly ride in the payload, not here.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.format_kind import FormatKind


@dataclass(slots=True)
class DownloadRequest:
    id: UUID
    user_id: UUID
    source_url: str
    media_type: MediaType = MediaType.UNKNOWN
    status: DownloadStatus = DownloadStatus.PENDING
    format_kind: FormatKind = FormatKind.VIDEO
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @classmethod
    def create(
        cls,
        user_id: UUID,
        source_url: str,
        format_kind: FormatKind = FormatKind.VIDEO,
    ) -> DownloadRequest:
        return cls(
            id=uuid4(),
            user_id=user_id,
            source_url=source_url,
            format_kind=format_kind,
        )

    def mark_processing(self) -> None:
        self.status = DownloadStatus.PROCESSING

    def mark_done(self) -> None:
        self.status = DownloadStatus.DONE
        self.completed_at = datetime.now(UTC)

    def mark_failed(self) -> None:
        self.status = DownloadStatus.FAILED
        self.completed_at = datetime.now(UTC)
