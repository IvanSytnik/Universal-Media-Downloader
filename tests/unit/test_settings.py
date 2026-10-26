"""Unit tests for Settings.

No network, no DB, no Redis — pure config logic. This is what
"domain/application must be 100% covered" looks like in practice:
cheap, fast, no external dependencies.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


# --- Day 11C (v2): DISABLED_FORMATS (FormatPolicy kill-switch) -----------------


def test_disabled_formats_default_is_empty() -> None:
    settings = Settings(bot_token="t", _env_file=None)  # type: ignore[arg-type, call-arg]
    assert settings.disabled_formats == {}


def test_disabled_formats_parses_env_json_and_lowercases_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISABLED_FORMATS", '{"YouTube": ["audio"], "tiktok": ["video", "audio"]}')
    settings = Settings(bot_token="t", _env_file=None)  # type: ignore[arg-type, call-arg]
    assert settings.disabled_formats == {"youtube": ["audio"], "tiktok": ["video", "audio"]}


def test_disabled_formats_rejects_unknown_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    # A typo must fail at startup, not silently leave the switch off.
    monkeypatch.setenv("DISABLED_FORMATS", '{"youtube": ["mp3"]}')
    with pytest.raises(ValidationError):
        Settings(bot_token="t", _env_file=None)  # type: ignore[arg-type, call-arg]


def test_preview_timeout_defaults_to_60_seconds() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.preview_timeout_seconds == 60


def test_preview_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(
            bot_token="test-token",  # type: ignore[arg-type]
            preview_timeout_seconds=0,
            _env_file=None,  # type: ignore[call-arg]
        )


def test_stale_request_grace_defaults_to_300_seconds() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.stale_request_grace_seconds == 300


def test_stale_request_grace_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(
            bot_token="test-token",  # type: ignore[arg-type]
            stale_request_grace_seconds=0,
            _env_file=None,  # type: ignore[call-arg]
        )


def test_download_min_free_disk_defaults_to_3_gb() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.download_min_free_disk_mb == 3072
    assert settings.download_min_free_disk_bytes == 3072 * 1024 * 1024


def test_download_min_free_disk_zero_disables_and_negative_is_rejected() -> None:
    disabled = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        download_min_free_disk_mb=0,
        _env_file=None,  # type: ignore[call-arg]
    )
    assert disabled.download_min_free_disk_bytes == 0

    with pytest.raises(ValidationError):
        Settings(
            bot_token="test-token",  # type: ignore[arg-type]
            download_min_free_disk_mb=-1,
            _env_file=None,  # type: ignore[call-arg]
        )


def test_observability_is_off_by_default() -> None:
    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.log_dir is None
    assert settings.sentry_dsn is None
    assert settings.log_file_max_bytes == 50 * 1024 * 1024
    assert settings.log_file_backups == 10


def test_log_rotation_bounds_are_validated() -> None:
    for field, value in (("log_file_max_mb", 0), ("log_file_backups", 0)):
        with pytest.raises(ValidationError):
            Settings(
                bot_token="test-token",  # type: ignore[arg-type]
                _env_file=None,  # type: ignore[call-arg]
                **{field: value},
            )


def test_blank_sentry_dsn_and_log_dir_mean_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "")
    monkeypatch.setenv("LOG_DIR", "  ")

    settings = Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.sentry_dsn is None
    assert settings.log_dir is None
