"""DownloadProgress — a point-in-time snapshot of an in-flight download.

Day 11B. Pure domain value object: no Telegram, no yt-dlp, no transport
concepts (chat_id/message_id/language are NOT here — those are delivery
routing details and stay in the payload that carries this object to
ProgressPublisherPort, see its docstring; contrast with format_kind,
which IS a domain property — PROJECT_SPEC §6.1 / TASK_Day11B.md).

``percent`` is None whenever ``total_bytes`` is None (a stream yt-dlp
can't size up front) — callers must render bytes/speed instead of a
percentage in that case, never assume percent is always available.

Day 11B.1: ``phase`` defaults to ``ProgressPhase.DOWNLOADING`` so every
pre-existing call site (tests included) that never mentions it keeps
constructing valid snapshots unchanged. ``ProgressPhase.CONVERTING``
marks the one-shot event at the download→postprocess boundary (audio
path only, see ytdlp_downloader.py) — when set, ``percent``/
``downloaded_bytes``/``total_bytes``/``speed``/``eta`` carry no meaningful
data and must not be rendered.

Day 11D-2: the same holds for ``UPLOADING`` / ``DONE`` / ``FAILED``;
``phase_marker`` builds such a data-less snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.value_objects.progress_phase import ProgressPhase


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    percent: float | None
    downloaded_bytes: int
    total_bytes: int | None
    speed: float | None
    eta: int | None
    phase: ProgressPhase = ProgressPhase.DOWNLOADING


def phase_marker(phase: ProgressPhase) -> DownloadProgress:
    """A one-shot phase event: no byte/percent data, only ``phase``."""
    return DownloadProgress(
        percent=None, downloaded_bytes=0, total_bytes=None, speed=None, eta=None, phase=phase
    )
