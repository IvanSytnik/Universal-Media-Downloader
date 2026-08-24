"""QualityKind — which video quality tier the user asked for (Day 11C).

Same shape and rationale as ``FormatKind``: a small domain ``StrEnum``
describing the user's INTENT, not the source's properties. "The user
asked for 1080p" is a property of the request (persisted, read back by
the worker), independent of what the source actually offers — if 1080p
isn't available, the extractor degrades on its own; that negotiation is
an infrastructure concern, not a domain one.

``max_height`` is the ONE place in the project that maps a tier to a
pixel height. The infrastructure downloader must read the height from
here rather than keeping a parallel dict — two mappings would drift the
moment a tier is added (a 4K tier would silently keep downloading 1080p).

``from_db_value`` exists because the database is an untrusted input at
this boundary: a row written by a newer version (or hand-edited) would
make the bare ``QualityKind(value)`` constructor raise ``ValueError``
deep inside the worker, killing a job that was already accepted from the
user. Degrading to the default tier is strictly better — same precedent
as ``ProgressPhase`` never being constructed from pubsub payloads (Day
11B). ``MediaType`` and ``FormatKind`` carry the same method for the
same reason.

The fallback is not logged here: only the repository knows WHICH row
held the bad value, and a warning without that id is unactionable. The
warning lives in ``_to_entity`` instead, which keeps the domain free of
a logging dependency.

Audio downloads ignore quality entirely; their rows carry the default
tier and nothing reads it (see the entity docstring).
"""

from __future__ import annotations

from enum import StrEnum


class QualityKind(StrEnum):
    HD_720 = "hd_720"
    HD_1080 = "hd_1080"

    @property
    def max_height(self) -> int:
        """Pixel height cap for this tier — the single source of truth."""
        match self:
            case QualityKind.HD_720:
                return 720
            case QualityKind.HD_1080:
                return 1080

    @classmethod
    def from_db_value(cls, value: str) -> QualityKind:
        """Parse a value read back from storage, degrading instead of raising.

        An unknown value means the row was written by something this code
        doesn't know about; falling back to the default tier keeps the
        download running (at a conservative quality) instead of failing a
        request the user has already been told was accepted.
        """
        try:
            return cls(value)
        except ValueError:
            return cls.HD_720
