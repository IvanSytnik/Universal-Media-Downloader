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

Day 11C stage 3 adds ``quality_kind``, and adds it HERE rather than in
stage 2 on purpose: a field nobody reads is bug 11A.1 committed on
purpose. It arrives together with the code that reads it
(``_build_download_ydl_opts`` via ``download``), so the write chain and
the read chain land in one commit.

The height itself is never stored here — only the tier. Infrastructure
asks ``QualityKind.max_height`` for the pixel value, so the tier→height
mapping stays in exactly one place (see quality_kind.py); a parallel
dict in the downloader would drift the first time a tier is added.

Irrelevant to ``FormatKind.AUDIO`` (no video stream to cap), where it is
simply ignored — mirroring the DB column, which mp3 rows also carry and
never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    output_dir: Path
    max_filesize_bytes: int | None = None
    timeout_seconds: int = 600
    format_kind: FormatKind = field(default=FormatKind.VIDEO)
    quality_kind: QualityKind = field(default=QualityKind.HD_720)
