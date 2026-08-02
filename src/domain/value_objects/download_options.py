"""Options for an actual download (Day 5), as opposed to a preview.

`output_dir` couples this value object to the filesystem — a pragmatic
compromise, not a pure domain concept. Noted as a tradeoff: a fully
"clean" design would express this as an abstract destination and let
infrastructure decide the concrete path. Given the project's current
scope (single local filesystem, no S3 yet — that's Phase 7), the extra
indirection isn't earning its cost today. Revisit if StoragePort grows
a second implementation.

Day 11A adds ``format_kind``: whether to fetch the video or extract just
the audio (mp3). It defaults to ``FormatKind.VIDEO`` so every existing
caller and test keeps its current behaviour without change — the audio
path is strictly opt-in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.domain.value_objects.format_kind import FormatKind


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    output_dir: Path
    max_filesize_bytes: int | None = None
    timeout_seconds: int = 600
    format_kind: FormatKind = field(default=FormatKind.VIDEO)
