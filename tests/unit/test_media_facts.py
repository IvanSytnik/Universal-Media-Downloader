"""Day 11D-1: the media facts a download returns.

The child reads them from yt-dlp's FINAL info (after merge/transcode)
and only runs ffprobe for what info lacks; they cross the process
boundary as JSON and come out as a DownloadResult. DeliverableMedia then
decides what is playable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.format_kind import FormatKind
from src.infrastructure.downloader import ytdlp_downloader
from src.infrastructure.downloader.ytdlp_downloader import (
    _ffprobe_facts,
    _media_facts,
    _parse_result,
)

# What yt-dlp's final info looks like after a bv*+ba merge: the merged
# format's fields are lifted onto the top level.
_MERGED_INFO: dict[str, Any] = {
    "title": "A Short",
    "uploader": "NASA",
    "width": 1080,
    "height": 1920,
    "duration": 37.8,
}


def _no_probe(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _probe(filename: str) -> dict[str, int]:
        calls.append(filename)
        return {"width": 640, "height": 360, "duration": 99}

    monkeypatch.setattr(ytdlp_downloader, "_ffprobe_facts", _probe)
    return calls


def test_video_facts_come_from_the_final_info(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _no_probe(monkeypatch)
    facts = _media_facts(_MERGED_INFO, "/out/v.mp4", FormatKind.VIDEO)
    assert facts == {
        "path": "/out/v.mp4",
        "width": 1080,
        "height": 1920,
        "duration_seconds": 38,
        "title": "A Short",
        "uploader": "NASA",
    }
    # Complete info: no extra process.
    assert calls == []


def test_ffprobe_fills_only_what_info_lacks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _no_probe(monkeypatch)
    info = {**_MERGED_INFO, "height": None}
    facts = _media_facts(info, "/out/v.mp4", FormatKind.VIDEO)
    assert calls == ["/out/v.mp4"]
    # Info's own values win; the probe only fills the gap.
    assert (facts["width"], facts["height"], facts["duration_seconds"]) == (1080, 360, 38)


def test_audio_has_no_dimensions_and_probes_only_for_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _no_probe(monkeypatch)
    facts = _media_facts(_MERGED_INFO, "/out/a.mp3", FormatKind.AUDIO)
    assert (facts["width"], facts["height"]) == (None, None)
    assert calls == []

    facts = _media_facts({"title": "t"}, "/out/a.mp3", FormatKind.AUDIO)
    assert facts["duration_seconds"] == 99
    assert (facts["width"], facts["height"]) == (None, None)


def test_performer_prefers_artist_then_uploader_then_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_probe(monkeypatch)
    base = {"duration": 10}
    assert _media_facts({**base, "channel": "C"}, "f", FormatKind.AUDIO)["uploader"] == "C"
    info = {**base, "artist": "A", "uploader": "U", "channel": "C"}
    assert _media_facts(info, "f", FormatKind.AUDIO)["uploader"] == "A"


@pytest.mark.parametrize("bad", [None, 0, -5, "1080", True])
def test_unusable_numbers_are_unknown_not_zero(monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    _no_probe(monkeypatch)
    facts = _media_facts({"width": bad, "height": 720, "duration": 5}, "f", FormatKind.VIDEO)
    # Probed, not trusted: a zero width would render a broken player.
    assert facts["width"] == 640


def test_payload_roundtrip_across_the_process_boundary() -> None:
    payload = json.dumps(
        {
            "path": "/out/v.mp4",
            "width": 1280,
            "height": 720,
            "duration_seconds": 2808,
            "title": "t",
            "uploader": None,
        }
    )
    assert _parse_result(payload) == DownloadResult(
        path=Path("/out/v.mp4"), width=1280, height=720, duration_seconds=2808, title="t"
    )


def test_ffprobe_failure_yields_no_facts(tmp_path: Path) -> None:
    not_media = tmp_path / "x.mp4"
    not_media.write_bytes(b"not a video")
    assert _ffprobe_facts(str(not_media)) == {}
    assert _ffprobe_facts(str(tmp_path / "missing.mp4")) == {}


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_ffprobe_reads_a_real_file(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x568:d=2",
            "-c:v",
            "libx264",
            str(clip),
        ],
        check=True,
        timeout=60,
    )
    assert _ffprobe_facts(str(clip)) == {"width": 320, "height": 568, "duration": 2}


# --- DeliverableMedia -------------------------------------------------------------


def test_deliverable_drops_dimensions_for_audio() -> None:
    result = DownloadResult(Path("a.mp3"), width=1920, height=1080, duration_seconds=5)
    media = DeliverableMedia.from_result(result, FormatKind.AUDIO)
    assert (media.width, media.height) == (None, None)
    assert media.is_playable_audio and not media.is_playable_video


def test_video_is_playable_only_with_every_fact() -> None:
    full = DownloadResult(Path("v.mp4"), width=1280, height=720, duration_seconds=5)
    assert DeliverableMedia.from_result(full, FormatKind.VIDEO).is_playable_video
    for gap in ({"width": None}, {"height": None}, {"duration_seconds": None}):
        partial = DownloadResult(
            Path("v.mp4"), **{"width": 1280, "height": 720, "duration_seconds": 5, **gap}
        )
        assert not DeliverableMedia.from_result(partial, FormatKind.VIDEO).is_playable_video
