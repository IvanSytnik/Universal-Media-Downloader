"""Health check interface. Domain layer — no implementation here."""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.health_report import HealthReport


class HealthCheckPort(Protocol):
    async def check(self) -> HealthReport:
        """Probe every external dependency. Must never raise: a failed
        probe is reported as ``False`` and its diagnostics are logged by
        the implementation."""
        ...
