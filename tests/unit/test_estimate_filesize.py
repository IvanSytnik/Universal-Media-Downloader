"""Tests for _estimate_total_filesize.

This function backs the proactive "too large to send" check that runs
BEFORE any bytes are downloaded (see _download_worker_entrypoint). It
replaced relying on yt-dlp's own `max_filesize` option, which was found
to abort downloads silently (no exception, just a leftover .part file)
when the limit is exceeded — indistinguishable from a real bug until
diagnostic logging (see test_missing_file_diagnostic.py) revealed it.
"""

from __future__ import annotations

from src.infrastructure.downloader.ytdlp_downloader import _estimate_total_filesize


def test_returns_none_for_none_info() -> None:
    assert _estimate_total_filesize(None) is None


def test_uses_top_level_filesize_when_no_requested_downloads() -> None:
    assert _estimate_total_filesize({"filesize": 1_000_000}) == 1_000_000


def test_falls_back_to_filesize_approx() -> None:
    assert _estimate_total_filesize({"filesize_approx": 2_000_000}) == 2_000_000


def test_sums_requested_downloads_when_all_sizes_known() -> None:
    info = {
        "requested_downloads": [
            {"filesize": 1_000_000},
            {"filesize_approx": 500_000},
        ]
    }
    assert _estimate_total_filesize(info) == 1_500_000


def test_returns_none_when_any_requested_download_size_unknown() -> None:
    info = {
        "requested_downloads": [
            {"filesize": 1_000_000},
            {},  # no size info at all — can't produce a safe total
        ]
    }
    assert _estimate_total_filesize(info) is None


def test_returns_none_when_no_size_fields_present() -> None:
    assert _estimate_total_filesize({"id": "abc"}) is None
