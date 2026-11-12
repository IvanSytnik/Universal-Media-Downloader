""".env.example is the configuration reference a new user copies; it must
parse and must not drift from Settings."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.config.settings import Settings

_ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def _documented_names() -> set[str]:
    # Active lines and commented-out examples ("# LOG_DIR=./logs") both count.
    pattern = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)
    return set(pattern.findall(_ENV_EXAMPLE.read_text(encoding="utf-8")))


def test_every_setting_is_documented() -> None:
    expected = {name.upper() for name in Settings.model_fields}
    missing = sorted(expected - _documented_names())
    assert not missing, f".env.example lacks: {missing}"


def test_minimal_profile_parses_as_copied(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("USE_LOCAL_BOT_API", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("MAX_DELIVERABLE_FILE_SIZE_MB", raising=False)
    settings = Settings(_env_file=_ENV_EXAMPLE)  # type: ignore[call-arg]
    assert settings.use_local_bot_api is False
    assert settings.max_deliverable_file_size_mb == 50


def test_full_profile_parses_once_filled_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USE_LOCAL_BOT_API", "true")
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "0123456789abcdef")
    monkeypatch.setenv("MAX_DELIVERABLE_FILE_SIZE_MB", "2000")
    settings = Settings(_env_file=_ENV_EXAMPLE)  # type: ignore[call-arg]
    assert settings.use_local_bot_api is True
    assert settings.telegram_api_id == 12345
