"""Test for configure_logging + get_logger integration.

This test exists specifically because a previous version shipped with
an incompatible processor/logger_factory pair (`add_logger_name`
processor requires a stdlib logger, but the factory produced
`PrintLogger`, which has no `.name`). That bug only surfaced at actual
runtime (`logger.info(...)`), not at import time — pytest didn't catch
it because nothing called the logger. This test closes that gap.
"""

from __future__ import annotations

from src.shared.logging import configure_logging, get_logger


def test_configure_logging_and_log_call_do_not_raise() -> None:
    configure_logging(log_level="INFO", environment="local")
    logger = get_logger("test")

    # This is the exact call that crashed in production (main.py startup log).
    logger.info("starting_bot", environment="local")
    logger.warning("test_warning", foo="bar")


def test_configure_logging_json_renderer_in_non_local_env() -> None:
    configure_logging(log_level="INFO", environment="production")
    logger = get_logger("test")

    logger.info("production_log_smoke_test")
