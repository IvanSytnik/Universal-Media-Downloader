"""DownloadProgress — pure domain value object. Day 11B."""

from __future__ import annotations

from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.progress_phase import ProgressPhase


def test_construction_with_all_fields() -> None:
    progress = DownloadProgress(
        percent=42.5, downloaded_bytes=1000, total_bytes=2000, speed=512.0, eta=10
    )
    assert progress.percent == 42.5
    assert progress.downloaded_bytes == 1000
    assert progress.total_bytes == 2000
    assert progress.speed == 512.0
    assert progress.eta == 10


def test_percent_none_for_unknown_total() -> None:
    progress = DownloadProgress(
        percent=None, downloaded_bytes=1000, total_bytes=None, speed=512.0, eta=None
    )
    assert progress.percent is None
    assert progress.total_bytes is None


def test_phase_defaults_to_downloading_for_existing_call_sites() -> None:
    # Every pre-Day-11B.1 call site omits `phase` entirely — this pins
    # that they keep constructing a valid, correctly-defaulted snapshot.
    progress = DownloadProgress(
        percent=42.5, downloaded_bytes=1000, total_bytes=2000, speed=512.0, eta=10
    )
    assert progress.phase is ProgressPhase.DOWNLOADING


def test_phase_can_be_set_to_converting() -> None:
    progress = DownloadProgress(
        percent=None,
        downloaded_bytes=0,
        total_bytes=None,
        speed=None,
        eta=None,
        phase=ProgressPhase.CONVERTING,
    )
    assert progress.phase is ProgressPhase.CONVERTING


def test_is_frozen() -> None:
    progress = DownloadProgress(
        percent=10.0, downloaded_bytes=1, total_bytes=10, speed=None, eta=None
    )
    try:
        progress.percent = 20.0  # type: ignore[misc]
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("DownloadProgress must be immutable")
