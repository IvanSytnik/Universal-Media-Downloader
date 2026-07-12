"""format_help and format_retry_after — pure functions (Day 8),
localized via i18n (Day 9)."""

from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.presentation.telegram.formatting import format_help, format_retry_after
from tests.conftest import FakeI18n


def _settings(**overrides: object) -> Settings:
    return Settings(bot_token="x", **overrides)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_help_lists_platforms_from_allowlist(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "ru")
    text = format_help(i18n, _settings(allowed_domains=["youtube.com", "tiktok.com"]))
    assert "youtube.com" in text
    assert "tiktok.com" in text


@pytest.mark.asyncio
async def test_help_reflects_configured_limits(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "ru")
    text = format_help(
        i18n, _settings(rate_limit_downloads_per_hour=7, max_deliverable_file_size_mb=123)
    )
    assert "7" in text
    assert "123" in text


@pytest.mark.asyncio
async def test_help_handles_empty_allowlist(i18n_core) -> None:
    # Empty allowlist = dev escape hatch (see Settings docstring) — help
    # must not render an empty platform list.
    i18n = FakeI18n(i18n_core, "ru")
    text = format_help(i18n, _settings(allowed_domains=[]))
    assert "yt-dlp" in text


@pytest.mark.asyncio
async def test_retry_after_seconds(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "ru")
    assert "сек" in format_retry_after(i18n, 45)


@pytest.mark.asyncio
async def test_retry_after_minutes_rounds_up(i18n_core) -> None:
    # 61s must say 2 min, never 1 — don't promise a shorter wait.
    i18n = FakeI18n(i18n_core, "ru")
    result = format_retry_after(i18n, 61)
    assert "2" in result
    assert "мин" in result
