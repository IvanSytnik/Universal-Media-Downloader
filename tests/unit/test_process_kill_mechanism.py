"""Real (not mocked) test of the kill-by-timeout mechanism.

Other tests monkeypatch `_run_download_in_process` to avoid spawning
real OS processes (slow, environment-dependent). This test is the
exception on purpose: the whole point of Day 5's process-isolation
design is that a hung child gets killed, not just "given up on" — that
guarantee is only real if we've actually watched a process die. Kept
separate from the yt-dlp-mocked tests, and slower by design (~1-2s).
"""

from __future__ import annotations

import multiprocessing
import time


def _sleep_forever_entrypoint(
    seconds: int, result_queue: multiprocessing.Queue[tuple[str, str]]
) -> None:
    time.sleep(seconds)
    result_queue.put(("ok", "should never get here"))


def _run_with_timeout(sleep_seconds: int, timeout_seconds: int) -> tuple[bool, float]:
    """Mirrors _run_download_in_process's kill logic exactly, but against
    a trivial sleeping target instead of yt-dlp — isolates the test from
    network/yt-dlp flakiness while still exercising real process spawn +
    terminate()."""
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue[tuple[str, str]] = ctx.Queue()
    process = ctx.Process(target=_sleep_forever_entrypoint, args=(sleep_seconds, result_queue))

    start = time.monotonic()
    process.start()
    process.join(timeout_seconds)

    was_killed = process.is_alive()
    if was_killed:
        process.terminate()
        process.join(5)

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
