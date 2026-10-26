"""DownloadResult — what a finished download produced (Day 11D-1).

The file plus the media facts the delivery needs, taken from the
extractor's FINAL info (after merge/transcode). Every fact is optional:
an extractor that doesn't report one leaves it None, and the delivery
falls back to a plain document rather than sending a video with made-up
dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    width: int | None = None
    height: int | None = None
    duration_seconds: int | None = None
    title: str | None = None
    uploader: str | None = None
