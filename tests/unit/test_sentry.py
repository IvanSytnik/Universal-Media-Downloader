"""Opt-in Sentry (ADR 0006): off without a DSN, the options it is
initialised with, ``before_send``'s tagging, and an end-to-end run
through the real logging config and SDK with a capturing transport.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.transport import Transport

from src.config.settings import Settings
from src.domain.exceptions import ContentUnavailableError, CorruptedRecordError
from src.infrastructure.observability import sentry
from src.shared.logging import bind_log_context, clear_log_context, configure_logging, get_logger

_DSN = "https://public@o0.ingest.sentry.io/0"


def _settings(**overrides: Any) -> Settings:
    return Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
        **overrides,
    )


def _record(**fields: Any) -> logging.LogRecord:
    """A stdlib record shaped like the ones structlog hands over."""
    record = logging.LogRecord("src.x", logging.ERROR, __file__, 1, fields, (), None)
    return record


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    clear_log_context()
    yield
    clear_log_context()


# --- opt-in ------------------------------------------------------------------


def test_off_without_a_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry.sentry_sdk, "init", lambda **kw: calls.append(kw))

    assert sentry.sentry_options(_settings(), "bot") is None
    assert sentry.init_sentry(_settings(), "bot") is False
    assert calls == []


def test_options_are_errors_only_and_private(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sentry.sentry_sdk, "init", lambda **kw: calls.append(kw))
    settings = _settings(sentry_dsn=_DSN, environment="production")

    assert sentry.init_sentry(settings, "worker") is True

    [options] = calls
    assert options["dsn"] == _DSN
    assert options["environment"] == "production"
    # PII stays at the SDK default (off); see the module docstring.
    assert not options.get("send_default_pii")
    assert options["include_local_variables"] is False
    assert options["traces_sample_rate"] == 0.0
    [integration] = options["integrations"]
    assert isinstance(integration, LoggingIntegration)


def test_dsn_is_secret_in_settings_repr() -> None:
    assert "public@" not in repr(_settings(sentry_dsn=_DSN))


# --- before_send -------------------------------------------------------------


def test_tags_and_message_come_from_the_log_record() -> None:
    before_send = sentry.make_before_send("worker")
    record = _record(
        event="process_download_corrupted_record",
        request_id="r-1",
        error_key="error-internal",
        column="status",
        raw_value="archived",
        level="error",
        logger="src.x",
        timestamp="2026-10-26T12:00:00Z",
    )

    event = before_send({"logentry": {"message": str(record.msg)}}, {"log_record": record})

    assert event is not None
    assert event["tags"] == {
        "service": "worker",
        "request_id": "r-1",
        "error_key": "error-internal",
    }
    # Groups by event name, not by the rendered dict with its ids in it.
    assert event["logentry"] == {"message": "process_download_corrupted_record", "params": []}
    assert event["extra"] == {"column": "status", "raw_value": "archived"}


def test_exception_attributes_become_tags() -> None:
    request_id, user_id = uuid4(), uuid4()
    exc = CorruptedRecordError(
        column="spec", raw_value="audio/p720", request_id=request_id, user_id=user_id
    )

    event = sentry.make_before_send("worker")({}, {"exc_info": (type(exc), exc, None)})

    assert event is not None
    assert event["tags"]["error_key"] == "error-internal"
    assert event["tags"]["request_id"] == str(request_id)


def test_bound_context_fills_what_the_record_does_not_have() -> None:
    bind_log_context(request_id="from-context", extractor_key="youtube", job="download_job")
    record = _record(event="boom", request_id="from-record")

    event = sentry.make_before_send("bot")({}, {"log_record": record})

    assert event is not None
    assert event["tags"] == {
        "service": "bot",
        "request_id": "from-record",  # the record wins
        "extractor_key": "youtube",
        "job": "download_job",
    }


def test_plain_exception_event_keeps_its_message() -> None:
    exc = RuntimeError("x")
    event = sentry.make_before_send("bot")(
        {"message": "x", "tags": {"existing": "1"}}, {"exc_info": (RuntimeError, exc, None)}
    )

    assert event is not None
    assert event["message"] == "x"
    assert "logentry" not in event
    assert event["tags"] == {"existing": "1", "service": "bot"}


# --- end to end --------------------------------------------------------------


class _CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture
def captured() -> Iterator[_CapturingTransport]:
    configure_logging(environment="production", service="worker")
    transport = _CapturingTransport()
    options = sentry.sentry_options(_settings(sentry_dsn=_DSN), "worker")
    assert options is not None
    sentry_sdk.init(**options, transport=transport)
    yield transport
    sentry_sdk.init()  # no DSN: an inactive client
    configure_logging(log_level="INFO", environment="local")


def test_structlog_error_becomes_a_tagged_event_and_warnings_do_not(
    captured: _CapturingTransport,
) -> None:
    bind_log_context(job="download_job", request_id="r-9")
    logger = get_logger("src.application.use_cases.process_download")

    logger.warning("process_download_failed", error_key="error-geo")
    logger.error("process_download_corrupted_record", column="status", raw_value="archived")

    [event] = captured.events
    assert event["logentry"]["message"] == "process_download_corrupted_record"
    assert event["tags"]["request_id"] == "r-9"
    assert event["tags"]["job"] == "download_job"
    assert event["tags"]["service"] == "worker"
    assert event["extra"]["column"] == "status"
    # The warning rode along as a breadcrumb, not as its own event.
    crumbs = [c.get("message") for c in event["breadcrumbs"]["values"]]
    assert any("process_download_failed" in (c or "") for c in crumbs)


def test_unhandled_exception_logged_by_a_framework_carries_domain_tags(
    captured: _CapturingTransport,
) -> None:
    bind_log_context(request_id="r-10", extractor_key="tiktok")
    try:
        raise ContentUnavailableError
    except ContentUnavailableError:
        logging.getLogger("aiogram.event").error("Cause exception", exc_info=sys.exc_info())

    [event] = captured.events
    assert event["exception"]["values"][-1]["type"] == "ContentUnavailableError"
    assert event["tags"]["error_key"] == "error-unavailable"
    assert event["tags"]["request_id"] == "r-10"
    assert event["tags"]["extractor_key"] == "tiktok"
    # No frame locals leave the process.
    for frame in event["exception"]["values"][-1]["stacktrace"]["frames"]:
        assert "vars" not in frame
