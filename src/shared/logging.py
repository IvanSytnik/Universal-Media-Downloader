"""Structured logging setup (structlog).

Called once at application startup (bot and, from Day 3, worker).
Produces JSON logs in production-like environments and readable
console output in local development.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(*, log_level: str = "INFO", environment: str = "local") -> None:
    """Configure structlog + stdlib logging to work together.

    In `local` environment, uses a human-readable console renderer.
    Otherwise, renders JSON — this is what should be shipped to
    log aggregation systems in staging/production (Phase 7).
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level.upper(),
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if environment == "local":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Thin wrapper so call sites don't import structlog directly."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
