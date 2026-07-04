"""Domain-level enums. Pure Python, no framework dependency."""

from __future__ import annotations

from enum import StrEnum


class DownloadStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class MediaType(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    PHOTO = "photo"
    UNKNOWN = "unknown"
