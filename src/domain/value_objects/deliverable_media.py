"""DeliverableMedia — a finished download as the notifier delivers it
(Day 11D-1).

Built by ProcessDownloadUseCase from the downloader's DownloadResult and
the request's spec: ``kind`` is what the user ASKED for (video / mp3),
the rest is what the file IS. The notifier picks the delivery method
from it — a playable video needs width, height and duration, an audio
track needs its duration; without them it falls back to a document.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.domain.value_objects.delivery_filename import delivery_filename
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.format_kind import FormatKind


@dataclass(frozen=True, slots=True)
class DeliverableMedia:
    path: Path
    kind: FormatKind
    width: int | None = None
    height: int | None = None
    duration_seconds: int | None = None
    title: str | None = None
    # The audio player's artist line; the source's uploader.
    performer: str | None = None

    @classmethod
    def from_result(cls, result: DownloadResult, kind: FormatKind) -> DeliverableMedia:
        return cls(
            path=result.path,
            kind=kind,
            # Dimensions describe a picture; an extracted audio track has none.
            width=result.width if kind is FormatKind.VIDEO else None,
            height=result.height if kind is FormatKind.VIDEO else None,
            duration_seconds=result.duration_seconds,
            title=result.title,
            performer=result.uploader,
        )

    @property
    def filename(self) -> str:
        """The name the recipient sees: the sanitized title, or the
        on-disk ``<id>.<ext>`` name when there is no usable title."""
        return delivery_filename(self.title, self.path)

    @property
    def is_playable_video(self) -> bool:
        return self.kind is FormatKind.VIDEO and None not in (
            self.width,
            self.height,
            self.duration_seconds,
        )

    @property
    def is_playable_audio(self) -> bool:
        return self.kind is FormatKind.AUDIO and self.duration_seconds is not None
