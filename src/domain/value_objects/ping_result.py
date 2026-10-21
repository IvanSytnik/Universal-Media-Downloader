"""PingResult — what the worker recorded for the last processed ping job."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PingResult:
    message: str
    processed_at: str
