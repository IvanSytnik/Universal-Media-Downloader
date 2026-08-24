"""Domain-level enums. Pure Python, no framework dependency.

``from_db_value`` on ``MediaType`` mirrors ``FormatKind`` and
``QualityKind``: the database is an untrusted input on the read path, so
a value this build doesn't recognize degrades to a truthful default
instead of raising ``ValueError`` deep inside the worker. The enums stay
free of logging on purpose — only the repository knows which row a bad
value came from, so it owns the warning (see _to_entity).

``DownloadStatus`` deliberately has NO ``from_db_value``: every one of
its members asserts something about work already done, so there is no
value that could stand in for a corrupt one without lying. The
repository raises ``CorruptedRecordError`` for it instead.
"""

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

    @classmethod
    def from_db_value(cls, value: str) -> MediaType:
        """Parse a stored value, degrading to UNKNOWN instead of raising.

        UNKNOWN is the honest fallback here: it already means "we have
        not determined what this is", which is exactly true of a value
        we cannot read. This enum is the most likely of the three to
        gain members later (photo/carousel work), so a rolling deploy
        writing a newer member must not break the older reader.
        """
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN
