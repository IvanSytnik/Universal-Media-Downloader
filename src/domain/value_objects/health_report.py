"""HealthReport — connectivity status of the external dependencies.

Deliberately booleans only: the raw failure reason (driver exception
text, hostnames, DSNs) belongs in the structured log, never in a reply
to a chat. Carrying it here would invite exactly that leak.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthReport:
    database_ok: bool
    cache_ok: bool

    @property
    def all_ok(self) -> bool:
        return self.database_ok and self.cache_ok
