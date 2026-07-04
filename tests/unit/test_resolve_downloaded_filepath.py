"""Tests for _resolve_downloaded_filepath.

Regression test for a real production bug: short videos (single combined
mp4 stream) worked, longer videos (separate video+audio streams merged
by ffmpeg) failed with FileNotFoundError, because
`ydl.prepare_filename(info)` predicts the filename from pre-merge info
and doesn't account for the merged container's actual extension.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.infrastructure.downloader.ytdlp_downloader import (
    _DownloadProcessError,
    _resolve_downloaded_filepath,
)


def test_uses_requested_downloads_filepath_when_present() -> None:
    ydl = MagicMock()
    info = {
        "requested_downloads": [{"filepath": "/tmp/umd-downloads/abc/video.mp4"}],
    }

    result = _resolve_downloaded_filepath(ydl, info)

    assert result == "/tmp/umd-downloads/abc/video.mp4"
    # Must not fall back to the unreliable pre-merge prediction when the
    # real path is available.
    ydl.prepare_filename.assert_not_called()


def test_falls_back_to_prepare_filename_when_requested_downloads_missing() -> None:
    ydl = MagicMock()
    ydl.prepare_filename.return_value = "/tmp/umd-downloads/abc/video.mp4"
    info = {"id": "abc"}

    result = _resolve_downloaded_filepath(ydl, info)

    assert result == "/tmp/umd-downloads/abc/video.mp4"
    ydl.prepare_filename.assert_called_once_with(info)


def test_falls_back_when_requested_downloads_entry_has_no_filepath() -> None:
    ydl = MagicMock()
    ydl.prepare_filename.return_value = "/tmp/umd-downloads/abc/video.mp4"
    info = {"requested_downloads": [{}]}

    result = _resolve_downloaded_filepath(ydl, info)

    assert result == "/tmp/umd-downloads/abc/video.mp4"


def test_raises_when_info_is_none() -> None:
    ydl = MagicMock()

    with pytest.raises(_DownloadProcessError):
        _resolve_downloaded_filepath(ydl, None)
