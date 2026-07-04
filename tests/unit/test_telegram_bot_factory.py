"""Tests for create_telegram_bot — verifies the local Bot API server
switch actually changes the session, without making real network calls
(constructing a Bot/AiohttpSession doesn't connect anywhere by itself).
"""

from __future__ import annotations

from src.config.settings import Settings
from src.infrastructure.telegram.bot_factory import create_telegram_bot


def _settings(**overrides: object) -> Settings:
    return Settings(
        bot_token="123456:test-token-abc",  # type: ignore[arg-type]  # must look like a real token — aiogram validates the format
        _env_file=None,  # type: ignore[call-arg]
        **overrides,  # type: ignore[arg-type]
    )


def test_default_bot_uses_default_telegram_api_base() -> None:
    bot = create_telegram_bot(_settings())

    # aiogram's default session points at api.telegram.org — we didn't
    # override it, so the session should be the library's own default,
    # not our local-server session.
    assert bot.session.api.base == "https://api.telegram.org/bot{token}/{method}"


def test_local_bot_api_enabled_points_session_at_local_server() -> None:
    bot = create_telegram_bot(
        _settings(use_local_bot_api=True, local_bot_api_base_url="http://test-server:8081")
    )

    assert "test-server:8081" in bot.session.api.base
    assert "api.telegram.org" not in bot.session.api.base
