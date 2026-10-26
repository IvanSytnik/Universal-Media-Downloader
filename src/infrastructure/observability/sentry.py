"""Opt-in Sentry error reporting (ops minimum, ADR 0006).

Off unless ``SENTRY_DSN`` is set. What becomes an event:

* ERROR-level log records (``LoggingIntegration``): our own
  ``logger.error`` calls, and the unhandled-exception logs aiogram and
  arq write with ``exc_info``. WARNINGs are breadcrumbs only: a
  geo-blocked or deleted video is an expected outcome, not a bug.
* Exceptions escaping an arq job (``ArqIntegration``, auto-enabled by
  the SDK when arq is installed). Sentry's dedupe drops the second
  report when arq also logs the same exception.

``before_send`` tags every event with the domain context, taken in this
order of precedence: the structured fields of the log record that caused
it (structlog hands stdlib the event dict as ``record.msg``), then
attributes of the exception (``error_key`` on every domain error,
``request_id`` on ``CorruptedRecordError``), then the context bound with
``bind_log_context``. Only a fixed set of keys becomes tags — low
cardinality, searchable. The rest of the record goes to ``extra``. The
message becomes the bare event name, so events group by event and not by
the URL or request id in the rendered dict.

Privacy: ``include_local_variables=False`` — frame locals in this
codebase hold settings, tokens and user URLs; the tags and the record's
own fields are the diagnostics we chose to send. PII collection stays at
the SDK default (off). It is deliberately not spelled out: the newest
SDKs deprecate ``send_default_pii`` for ``data_collection``, which the
older versions in our pin range would reject.
No tracing (``traces_sample_rate=0``): errors only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from importlib import metadata
from typing import Any

import sentry_sdk
import structlog
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.types import Event, Hint

from src.config.settings import Settings

TAG_KEYS = ("request_id", "error_key", "extractor_key", "job")

# structlog/stdlib bookkeeping that is not diagnostic content.
_RECORD_META = frozenset(
    {
        "event",
        "level",
        "logger",
        "timestamp",
        "exc_info",
        "stack_info",
        "_record",
        "_from_structlog",
    }
)


def _log_fields(hint: Hint) -> Mapping[str, Any]:
    record = hint.get("log_record")
    if isinstance(record, logging.LogRecord) and isinstance(record.msg, dict):
        return record.msg
    return {}


def _exception(hint: Hint) -> BaseException | None:
    exc_info = hint.get("exc_info")
    if isinstance(exc_info, tuple) and len(exc_info) == 3:
        exc = exc_info[1]
        return exc if isinstance(exc, BaseException) else None
    return None


def make_before_send(service: str) -> Callable[[Event, Hint], Event | None]:
    def before_send(event: Event, hint: Hint) -> Event | None:
        fields = _log_fields(hint)
        exc = _exception(hint)
        context = structlog.contextvars.get_contextvars()

        tags: dict[str, Any] = dict(event.get("tags") or {})
        tags["service"] = service
        for key in TAG_KEYS:
            value = fields.get(key, getattr(exc, key, None))
            if value is None:
                value = context.get(key)
            if value is not None:
                tags[key] = str(value)
        event["tags"] = tags

        if fields:
            event["logentry"] = {"message": str(fields.get("event", "")), "params": []}
            extra = dict(event.get("extra") or {})
            extra.update(
                {k: v for k, v in fields.items() if k not in _RECORD_META and k not in TAG_KEYS}
            )
            event["extra"] = extra
        return event

    return before_send


def _release() -> str | None:
    try:
        return f"umd@{metadata.version('universal-media-downloader')}"
    except metadata.PackageNotFoundError:
        return None


def sentry_options(settings: Settings, service: str) -> dict[str, Any] | None:
    """The ``sentry_sdk.init`` keyword arguments, or None when Sentry is
    off. Split from ``init_sentry`` so tests can init with a capturing
    transport on top of exactly these options."""
    if settings.sentry_dsn is None:
        return None
    return {
        "dsn": settings.sentry_dsn.get_secret_value(),
        "environment": settings.environment,
        "release": _release(),
        "include_local_variables": False,
        "traces_sample_rate": 0.0,
        "integrations": [LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        "before_send": make_before_send(service),
    }


def init_sentry(settings: Settings, service: str) -> bool:
    """Initialise Sentry for this process if configured. Call after
    ``configure_logging``. Returns whether it is on."""
    options = sentry_options(settings, service)
    if options is None:
        return False
    sentry_sdk.init(**options)
    return True
