"""Real (not mocked) test of the kill-by-timeout mechanism.

Other tests monkeypatch `_run_download_in_process` to avoid spawning
real OS processes (slow, environment-dependent). This test is the
exception on purpose: the whole point of Day 5's process-isolation
design is that a hung child gets killed, not just "given up on" — that
guarantee is only real if we've actually watched a process die.

Day 11B: this used to keep its OWN hand-copied mirror of
`_run_download_in_process`'s wait/terminate logic (to dodge spawning a
real yt-dlp-shaped child), which meant a regression in the REAL
timeout/terminate path could slip through unnoticed — the test would
keep passing against its own stale copy. The Day 11B refactor pulled
that exact logic out into `_wait_and_drain_progress`, callable on its
own against any real spawned process — so this test now calls THE
SHIPPED FUNCTION directly instead of maintaining a parallel copy. Same
two assertions as before, now pinned against real code, not a mirror.
Kept separate from the yt-dlp-mocked tests, and slower by design (~1-2s).
"""

from __future__ import annotations

import multiprocessing
import time

from src.infrastructure.downloader import ytdlp_downloader


def _sleep_forever_entrypoint(
    seconds: int, result_queue: multiprocessing.Queue[tuple[str, str]]
) -> None:
    time.sleep(seconds)
    result_queue.put(("ok", "should never get here"))


def _run_with_timeout(sleep_seconds: int, timeout_seconds: int) -> tuple[bool, float]:
    """Spawns a real trivial sleeping process (isolated from
    network/yt-dlp flakiness) and drives it through the REAL
    `_wait_and_drain_progress` — the exact function `_run_download_in_process`
    uses in production."""
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue[tuple[str, str]] = ctx.Queue()
    progress_queue: multiprocessing.Queue[dict[str, object]] = ctx.Queue()
    process = ctx.Process(target=_sleep_forever_entrypoint, args=(sleep_seconds, result_queue))

    start = time.monotonic()
    process.start()
    try:
        ytdlp_downloader._wait_and_drain_progress(process, progress_queue, None, timeout_seconds)
        was_killed = False
    except ytdlp_downloader._DownloadTimeoutError:
        was_killed = True
    elapsed = time.monotonic() - start

    return was_killed, elapsed


def test_hung_process_is_killed_within_timeout() -> None:
    was_killed, elapsed = _run_with_timeout(sleep_seconds=10, timeout_seconds=1)

    assert was_killed is True
    # Should terminate close to the 1s timeout, not wait anywhere near
    # the 10s sleep — this is the actual guarantee being tested.
    assert elapsed < 5


def test_fast_process_completes_without_being_killed() -> None:
    was_killed, elapsed = _run_with_timeout(sleep_seconds=0, timeout_seconds=5)

    assert was_killed is False
    assert elapsed < 5
