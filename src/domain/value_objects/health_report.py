"""HealthReport — connectivity status of the external dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HealthReport:
    database_ok: bool
    cache_ok: bool
    database_error: str | None = None
    cache_error: str | None = None

    @property
    def all_ok(self) -> bool:
        return self.database_ok and self.cache_ok
