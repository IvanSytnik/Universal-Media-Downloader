"""format_help and format_retry_after (Day 8) — pure functions."""

from __future__ import annotations

from src.config.settings import Settings
from src.presentation.telegram.formatting import format_help, format_retry_after


def _settings(**overrides: object) -> Settings:
    return Settings(bot_token="x", **overrides)  # type: ignore[arg-type]


def test_help_lists_platforms_from_allowlist() -> None:
    text = format_help(_settings(allowed_domains=["youtube.com", "tiktok.com"]))
    assert "youtube.com" in text
    assert "tiktok.com" in text


def test_help_reflects_configured_limits() -> None:
    text = format_help(
        _settings(rate_limit_downloads_per_hour=7, max_deliverable_file_size_mb=123)
    )
    assert "7" in text
    assert "123" in text


def test_help_handles_empty_allowlist() -> None:
    # Empty allowlist = dev escape hatch (see Settings docstring) — help
    # must not render an empty platform list.
    text = format_help(_settings(allowed_domains=[]))
    assert "yt-dlp" in text


def test_retry_after_seconds() -> None:
    assert "45 сек" in format_retry_after(45)


def test_retry_after_minutes_rounds_up() -> None:
    # 61s must say 2 min, never 1 — don't promise a shorter wait.
    assert "2 мин" in format_retry_after(61)
