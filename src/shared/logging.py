"""Structured logging setup (structlog).

Called once at application startup (bot and, from Day 3, worker).
Produces JSON logs in production-like environments and readable
console output in local development.

Persistent logs (ops minimum, ADR 0006). Container stdout is gone after
``docker compose down`` / a recreate, and with it the diagnostics of the
failure that prompted the restart. With ``log_dir`` set, every record is
also written as one JSON object per line to ``<log_dir>/<service>.log``,
rotated by size. One file per service: ``RotatingFileHandler`` is not
safe across processes, and the bot and the worker are separate ones.

Both outputs hang off the stdlib root logger through structlog's
``ProcessorFormatter``: structlog events are handed to stdlib unrendered
and each handler renders them its own way (console or JSON on stdout,
always JSON in the file). Records from third-party stdlib loggers
(aiogram, arq, SQLAlchemy) go through the same pre-chain, so they reach
the file too, with timestamps, levels and the bound context.

``bind_log_context`` is the one way to attach domain context (request
id, extractor, job). It binds structlog contextvars, so the values ride
on every log line in the current asyncio task and on its Sentry events
(see infrastructure/observability/sentry.py). Each arq job and each
aiogram update runs in its own task, so context does not leak between
them.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

import structlog

# Marks handlers this module installed, so a second configure_logging()
# (tests, a re-run) replaces them instead of stacking duplicates.
_OWNED = "_umd_owned"

_PRE_CHAIN: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
]


def _formatter(renderer: structlog.types.Processor) -> structlog.stdlib.ProcessorFormatter:
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_PRE_CHAIN,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
    )


def _own(handler: logging.Handler) -> logging.Handler:
    setattr(handler, _OWNED, True)
    return handler


def configure_logging(
    *,
    log_level: str = "INFO",
    environment: str = "local",
    service: str = "app",
    log_dir: Path | None = None,
    log_file_max_bytes: int = 50 * 1024 * 1024,
    log_file_backups: int = 10,
) -> None:
    """Configure structlog + stdlib logging to work together.

    In `local` environment, stdout uses a human-readable console
    renderer. Otherwise, renders JSON — this is what should be shipped
    to log aggregation systems in staging/production (Phase 7).

    ``log_dir`` adds the rotating JSON file ``<log_dir>/<service>.log``.
    If it can't be opened, logging carries on to stdout and says so: a
    misconfigured log volume must not take the bot down with it.
    """
    root = logging.getLogger()
    for handler in [h for h in root.handlers if getattr(h, _OWNED, False)]:
        root.removeHandler(handler)
        handler.close()
    root.setLevel(log_level.upper())

    console: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer()
        if environment == "local"
        else structlog.processors.JSONRenderer()
    )
    stdout = _own(logging.StreamHandler(sys.stdout))
    stdout.setFormatter(_formatter(console))
    root.addHandler(stdout)

    file_error: OSError | None = None
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = _own(
                logging.handlers.RotatingFileHandler(
                    log_dir / f"{service}.log",
                    maxBytes=log_file_max_bytes,
                    backupCount=log_file_backups,
                    encoding="utf-8",
                )
            )
        except OSError as exc:
            file_error = exc
        else:
            file_handler.setFormatter(_formatter(structlog.processors.JSONRenderer()))
            root.addHandler(file_handler)

    structlog.configure(
        processors=[*_PRE_CHAIN, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    if file_error is not None:
        get_logger(__name__).warning(
            "log_file_unavailable", log_dir=str(log_dir), error=str(file_error)
        )


def bind_log_context(**values: str) -> None:
    """Attach domain context to every log line (and Sentry event) for
    the rest of the current asyncio task."""
    structlog.contextvars.bind_contextvars(**values)


def clear_log_context() -> None:
    """Start a unit of work (a job) with no context left over."""
    structlog.contextvars.clear_contextvars()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Thin wrapper so call sites don't import structlog directly."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
