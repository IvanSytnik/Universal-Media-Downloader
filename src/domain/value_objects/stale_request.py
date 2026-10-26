"""StaleRequest — a download request the reaper moved to FAILED.

Carries only what the reaper needs after the transition: who to tell
(``user_id``) and what the request was doing when it stalled
(``previous_status`` — PENDING means the job never started, PROCESSING
that it started and never finished). The transition itself is already
committed when this exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.domain.value_objects.enums import DownloadStatus


@dataclass(frozen=True, slots=True)
class StaleRequest:
    request_id: UUID
    user_id: UUID
    previous_status: DownloadStatus
