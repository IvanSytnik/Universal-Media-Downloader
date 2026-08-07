"""ProgressThrottler — pure debounce logic (1/3s AND >=5% step). Day 11B."""

from __future__ import annotations

from src.presentation.telegram.progress_listener import ProgressThrottler


def test_first_update_for_a_key_always_emits() -> None:
    throttler = ProgressThrottler()
    assert throttler.should_emit("req-1", percent=10.0, now=0.0) is True


def test_suppressed_within_min_interval_even_with_big_percent_jump() -> None:
    throttler = ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0)
    throttler.should_emit("req-1", percent=10.0, now=0.0)

    assert throttler.should_emit("req-1", percent=50.0, now=1.0) is False


def test_suppressed_after_interval_if_percent_step_too_small() -> None:
    throttler = ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0)
    throttler.should_emit("req-1", percent=10.0, now=0.0)

    assert throttler.should_emit("req-1", percent=12.0, now=5.0) is False


def test_emits_when_both_interval_and_step_satisfied() -> None:
    throttler = ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0)
    throttler.should_emit("req-1", percent=10.0, now=0.0)

    assert throttler.should_emit("req-1", percent=16.0, now=5.0) is True


def test_none_percent_is_time_throttled_only() -> None:
    # Streams without a known total: no percent to compare, so interval
    # alone gates emission.
    throttler = ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0)
    throttler.should_emit("req-1", percent=None, now=0.0)

    assert throttler.should_emit("req-1", percent=None, now=1.0) is False
    assert throttler.should_emit("req-1", percent=None, now=4.0) is True


def test_independent_keys_do_not_interfere() -> None:
    throttler = ProgressThrottler()
    throttler.should_emit("req-1", percent=10.0, now=0.0)

    assert throttler.should_emit("req-2", percent=10.0, now=0.1) is True


def test_discard_resets_state_for_key() -> None:
    throttler = ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0)
    throttler.should_emit("req-1", percent=10.0, now=0.0)
    throttler.discard("req-1")

    # Treated as a brand-new key again — emits immediately.
    assert throttler.should_emit("req-1", percent=11.0, now=0.5) is True
