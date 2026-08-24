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

Day 11C adds ``quality_kind`` for the same reason: the worker rebuilds
the request from the database by id, so the requested video quality has
to be persisted to be visible to it. It is NOT nullable and defaults to
``HD_720``: audio (mp3) requests carry the default and simply never read
it — quality is meaningless for an extracted audio track, and a nullable
column would push that "not applicable" case onto every read site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind


@dataclass(slots=True)
class DownloadRequest:
    id: UUID
    user_id: UUID
    source_url: str
    media_type: MediaType = MediaType.UNKNOWN
    status: DownloadStatus = DownloadStatus.PENDING
    format_kind: FormatKind = FormatKind.VIDEO
    quality_kind: QualityKind = QualityKind.HD_720
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @classmethod
    def create(
        cls,
        user_id: UUID,
        source_url: str,
        format_kind: FormatKind = FormatKind.VIDEO,
        quality_kind: QualityKind = QualityKind.HD_720,
    ) -> DownloadRequest:
        return cls(
            id=uuid4(),
            user_id=user_id,
            source_url=source_url,
            format_kind=format_kind,
            quality_kind=quality_kind,
        )

    def mark_processing(self) -> None:
        self.status = DownloadStatus.PROCESSING

    def mark_done(self) -> None:
        self.status = DownloadStatus.DONE
        self.completed_at = datetime.now(UTC)

    def mark_failed(self) -> None:
        self.status = DownloadStatus.FAILED
        self.completed_at = datetime.now(UTC)
