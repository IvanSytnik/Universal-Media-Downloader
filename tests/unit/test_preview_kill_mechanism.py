"""Real (not mocked) test of the preview kill switch — the preview
counterpart of test_process_kill_mechanism.py, same reasoning: the
guarantee that a stalled extraction gives the executor thread back is
only real if we've watched the child die.

The children run in the production context (`_preview_context()`, a
forkserver), so these also pin that the forkserver path works at all.
The last test drives the whole `_run_preview_in_process` with real
yt-dlp in the child, on input it rejects without touching the network.
"""

from __future__ import annotations

import multiprocessing
import time
from typing import Any

import pytest

from src.infrastructure.downloader import ytdlp_downloader


def _sleep_then_report(
    seconds: float, result_queue: multiprocessing.Queue[tuple[str, Any]]
) -> None:
    time.sleep(seconds)
    result_queue.put(("ok", {"slept": seconds}))


def _exit_without_result(result_queue: multiprocessing.Queue[tuple[str, Any]]) -> None:
    raise SystemExit(3)


def _collect(target: Any, args: tuple[Any, ...], timeout_seconds: float) -> tuple[Any, float, Any]:
    ctx = ytdlp_downloader._preview_context()
    result_queue: multiprocessing.Queue[tuple[str, Any]] = ctx.Queue()
    process = ctx.Process(target=target, args=(*args, result_queue))
    start = time.monotonic()
    process.start()
    try:
        outcome: Any = ytdlp_downloader._collect_preview_result(
            process, result_queue, timeout_seconds
        )
    except Exception as exc:
        outcome = exc
    return outcome, time.monotonic() - start, process


def test_hung_preview_child_is_killed_within_timeout() -> None:
    outcome, elapsed, process = _collect(_sleep_then_report, (30,), timeout_seconds=1)

    assert isinstance(outcome, ytdlp_downloader._PreviewTimeoutError)
    assert elapsed < 5
    assert not process.is_alive()


def test_fast_preview_child_returns_its_result() -> None:
    outcome, elapsed, process = _collect(_sleep_then_report, (0,), timeout_seconds=10)

    assert outcome == ("ok", {"slept": 0})
    assert elapsed < 5
    assert not process.is_alive()


def test_child_exiting_without_result_fails_fast_not_at_timeout() -> None:
    outcome, elapsed, process = _collect(_exit_without_result, (), timeout_seconds=30)

    assert isinstance(outcome, ytdlp_downloader._DownloadProcessError)
    assert "exit code 3" in str(outcome)
    assert elapsed < 5


def test_real_runner_reports_ytdlp_error_from_the_child() -> None:
    with pytest.raises(ytdlp_downloader._DownloadExtractError, match="not a valid URL"):
        ytdlp_downloader._run_preview_in_process("not-a-url", 30)
