"""Options for an actual download (Day 5), as opposed to a preview.

`output_dir` couples this value object to the filesystem — a pragmatic
compromise, not a pure domain concept. Noted as a tradeoff: a fully
"clean" design would express this as an abstract destination and let
infrastructure decide the concrete path. Given the project's current
scope (single local filesystem, no S3 yet — that's Phase 7), the extra
indirection isn't earning its cost today. Revisit if StoragePort grows
a second implementation.

Day 11A added ``format_kind`` and Day 11C ``quality_kind``; Day 11C (v2)
replaces both with ``spec: DownloadSpec``, copied verbatim from the
request by ProcessDownloadUseCase (the 11A.1 link — guarded by an
argument-capture test). The pixel value is never stored here: the
downloader asks ``VideoTier.short_side``, the single tier→pixels
mapping (see download_spec.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.domain.value_objects.download_spec import DEFAULT_DOWNLOAD_SPEC, DownloadSpec


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    output_dir: Path
    max_filesize_bytes: int | None = None
    timeout_seconds: int = 600
    spec: DownloadSpec = DEFAULT_DOWNLOAD_SPEC
