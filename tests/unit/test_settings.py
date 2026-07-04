"""Unit tests for Settings.

No network, no DB, no Redis — pure config logic. This is what
"domain/application must be 100% covered" looks like in practice:
cheap, fast, no external dependencies.
"""

from __future__ import annotations

from src.config.settings import Settings


def test_settings_builds_postgres_dsn() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        postgres_host="db.example.com",
        postgres_port=5433,
        postgres_db="testdb",
        postgres_user="testuser",
        postgres_password="testpass",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]  # don't read a real .env in tests
    )

    assert settings.postgres_dsn == "postgresql://testuser:testpass@db.example.com:5433/testdb"


def test_settings_builds_redis_dsn() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        redis_host="cache.example.com",
        redis_port=6380,
        redis_db=2,
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.redis_dsn == "redis://cache.example.com:6380/2"


def test_bot_token_is_not_leaked_in_repr() -> None:
    settings = Settings(
        bot_token="super-secret-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert "super-secret-token" not in repr(settings)
    assert "super-secret-token" not in str(settings)


def test_default_max_deliverable_file_size_is_50mb() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.max_deliverable_file_size_mb == 50
    assert settings.max_deliverable_file_size_bytes == 50 * 1024 * 1024


def test_max_deliverable_file_size_bytes_respects_override() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        max_deliverable_file_size_mb=2000,
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.max_deliverable_file_size_bytes == 2000 * 1024 * 1024


def test_use_local_bot_api_defaults_to_false() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.use_local_bot_api is False
    assert settings.local_bot_api_base_url == "http://telegram-bot-api:8081"
