"""Operational commands: admin allowlist and sanitized /health output.

Two security properties are pinned here:
1. ``AdminOnly`` fails closed — empty allowlist, unknown user, or no sender
   at all means no access.
2. Nothing raw from a failed health probe reaches a chat. The DSN-looking
   secret below must show up in the structured log and nowhere in the
   reply, even for an admin.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import structlog
from aiogram.types import Chat, Message, User

from src.config.settings import Settings
from src.domain.value_objects.health_report import HealthReport
from src.domain.value_objects.ping_result import PingResult
from src.infrastructure import health as health_module
from src.infrastructure.health import ConnectivityHealthCheck
from src.presentation.telegram.filters import AdminOnly
from src.presentation.telegram.handlers.admin import (
    handle_admin_command_denied,
    handle_health,
    handle_worker_status,
    router,
)
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core
from tests.conftest import FakeI18n

ADMIN_ID = 1001
SECRET = "postgresql://umd:s3cr3t@db.internal:5432/umd"


def _settings(**overrides: Any) -> Settings:
    return Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
        **overrides,
    )


class _Message(Message):
    """A real aiogram Message with ``answer`` captured."""

    @property
    def answers(self) -> list[str]:
        return self.__dict__.setdefault("_answers", [])

    async def answer(self, text: str, **kwargs: Any) -> None:  # type: ignore[override]
        self.answers.append(text)


def _message(text: str, user_id: int | None = ADMIN_ID) -> _Message:
    return _Message.model_construct(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        from_user=(User(id=user_id, is_bot=False, first_name="t") if user_id is not None else None),
        text=text,
    )


@pytest.fixture
async def i18n() -> Any:
    core = create_i18n_core()
    await core.startup()
    return FakeI18n(core, DEFAULT_LOCALE)


# --- settings ------------------------------------------------------------------


def test_admin_list_defaults_to_empty() -> None:
    assert _settings().admin_telegram_ids_set == frozenset()


def test_admin_list_parses_json_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "[1001, 2002]")
    assert _settings().admin_telegram_ids_set == frozenset({1001, 2002})


# --- AdminOnly -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_passes() -> None:
    settings = _settings(admin_telegram_ids=[ADMIN_ID])
    assert await AdminOnly()(_message("/health"), settings) is True


@pytest.mark.asyncio
async def test_non_admin_is_denied() -> None:
    settings = _settings(admin_telegram_ids=[ADMIN_ID])
    assert await AdminOnly()(_message("/health", user_id=42), settings) is False


@pytest.mark.asyncio
async def test_empty_allowlist_denies_everyone() -> None:
    assert await AdminOnly()(_message("/health"), _settings()) is False


@pytest.mark.asyncio
async def test_message_without_sender_is_denied() -> None:
    settings = _settings(admin_telegram_ids=[ADMIN_ID])
    assert await AdminOnly()(_message("/health", user_id=None), settings) is False


# --- denial handler --------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_command_is_consumed_silently_and_logged() -> None:
    message = _message("/health extra", user_id=42)

    with structlog.testing.capture_logs() as logs:
        await handle_admin_command_denied(message)

    assert message.answers == []
    assert logs == [
        {
            "event": "admin_command_denied",
            "log_level": "warning",
            "telegram_id": 42,
            "command": "/health",
        }
    ]


# --- /health sanitization ------------------------------------------------------------


class _FakeHealthCheck:
    def __init__(self, report: HealthReport) -> None:
        self._report = report

    async def check(self) -> HealthReport:
        return self._report


@pytest.mark.asyncio
async def test_health_reports_ok_components(i18n: Any) -> None:
    message = _message("/health")
    await handle_health(message, i18n, _FakeHealthCheck(HealthReport(True, True)))

    assert message.answers == ["Postgres: ✅ OK\nRedis: ✅ OK"]


@pytest.mark.asyncio
async def test_health_reports_failure_as_clean_indicator(i18n: Any) -> None:
    message = _message("/health")
    await handle_health(message, i18n, _FakeHealthCheck(HealthReport(False, True)))

    assert message.answers == ["Postgres: ❌ Unavailable\nRedis: ✅ OK"]


@pytest.mark.asyncio
async def test_probe_diagnostics_are_logged_never_replied(
    i18n: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through the real ConnectivityHealthCheck: the raw error
    lands in the log and is absent from what the admin sees."""

    async def _failing_postgres(settings: Settings) -> tuple[bool, str | None]:
        return False, f"connection to {SECRET} refused"

    async def _ok_redis(settings: Settings) -> tuple[bool, str | None]:
        return True, None

    monkeypatch.setattr(health_module, "check_postgres", _failing_postgres)
    monkeypatch.setattr(health_module, "check_redis", _ok_redis)
    message = _message("/health")

    with structlog.testing.capture_logs() as logs:
        await handle_health(message, i18n, ConnectivityHealthCheck(_settings()))

    assert message.answers == ["Postgres: ❌ Unavailable\nRedis: ✅ OK"]
    assert all(SECRET not in answer for answer in message.answers)
    failures = [entry for entry in logs if entry["event"] == "health_check_failed"]
    assert failures == [
        {
            "event": "health_check_failed",
            "log_level": "warning",
            "component": "postgres",
            "error": f"connection to {SECRET} refused",
        }
    ]


def test_health_report_has_no_field_that_could_carry_diagnostics() -> None:
    assert set(HealthReport.__dataclass_fields__) == {"database_ok", "cache_ok"}
    assert HealthReport(True, True).all_ok
    assert not HealthReport(True, False).all_ok


# --- /worker_status ----------------------------------------------------------------


class _FakePingReader:
    def __init__(self, result: PingResult | None) -> None:
        self._result = result

    async def get_last(self) -> PingResult | None:
        return self._result


@pytest.mark.asyncio
async def test_worker_status_without_ping(i18n: Any) -> None:
    message = _message("/worker_status")
    await handle_worker_status(message, i18n, _FakePingReader(None))

    assert message.answers == [i18n.get("worker-status-empty")]


@pytest.mark.asyncio
async def test_worker_status_escapes_the_recorded_message(i18n: Any) -> None:
    message = _message("/worker_status")
    result = PingResult(message="<b>hi</b>", processed_at="2026-10-21T00:00:00+00:00")

    await handle_worker_status(message, i18n, _FakePingReader(result))

    assert len(message.answers) == 1
    assert "&lt;b&gt;hi&lt;/b&gt;" in message.answers[0]
    assert "<b>hi</b>" not in message.answers[0]


# --- routing through the real router (filter injection + ordering) --------------


async def _route(text: str, user_id: int, i18n: Any) -> tuple[_Message, list[Any]]:
    """Propagate a message through the real admin router, with workflow data
    passed the way the dispatcher does. Proves aiogram injects ``settings``
    into ``AdminOnly`` and that non-admins land on the denial handler."""
    message = _message(text, user_id=user_id)
    with structlog.testing.capture_logs() as logs:
        await router.propagate_event(
            "message",
            message,
            bot=object(),
            i18n=i18n,
            settings=_settings(admin_telegram_ids=[ADMIN_ID]),
            health_check=_FakeHealthCheck(HealthReport(True, False)),
        )
    return message, logs


@pytest.mark.asyncio
async def test_router_serves_health_to_admin(i18n: Any) -> None:
    message, logs = await _route("/health", ADMIN_ID, i18n)

    assert message.answers == ["Postgres: ✅ OK\nRedis: ❌ Unavailable"]
    assert not any(entry["event"] == "admin_command_denied" for entry in logs)


@pytest.mark.asyncio
async def test_router_denies_health_to_non_admin(i18n: Any) -> None:
    message, logs = await _route("/health", 42, i18n)

    assert message.answers == []
    assert [entry["event"] for entry in logs] == ["admin_command_denied"]
