"""Test for configure_logging + get_logger integration.

This test exists specifically because a previous version shipped with
an incompatible processor/logger_factory pair (`add_logger_name`
processor requires a stdlib logger, but the factory produced
`PrintLogger`, which has no `.name`). That bug only surfaced at actual
runtime (`logger.info(...)`), not at import time — pytest didn't catch
it because nothing called the logger. This test closes that gap.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import structlog

from src.shared.logging import (
    bind_log_context,
    clear_log_context,
    configure_logging,
    describe_error,
    get_logger,
)


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


# --- persistent file logs (ADR 0006) -----------------------------------------


@pytest.fixture
def restore_logging() -> Iterator[None]:
    """Each test configures the process-wide root logger; put back a
    plain stdout config (closing any file handler) afterwards."""
    clear_log_context()
    yield
    clear_log_context()
    configure_logging(log_level="INFO", environment="local")


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.usefixtures("restore_logging")
def test_file_log_is_json_lines_with_bound_context(tmp_path: Path) -> None:
    configure_logging(environment="local", service="worker", log_dir=tmp_path)
    bind_log_context(request_id="r-1", job="download_job")

    get_logger("src.test").warning("process_download_failed", error_key="error-geo")

    [line] = _lines(tmp_path / "worker.log")
    assert line["event"] == "process_download_failed"
    assert line["error_key"] == "error-geo"
    assert line["request_id"] == "r-1"
    assert line["job"] == "download_job"
    assert line["level"] == "warning"
    assert line["logger"] == "src.test"
    assert "timestamp" in line


@pytest.mark.usefixtures("restore_logging")
def test_third_party_stdlib_records_reach_the_file(tmp_path: Path) -> None:
    configure_logging(environment="production", service="bot", log_dir=tmp_path)
    bind_log_context(request_id="r-2")

    logging.getLogger("aiogram.event").error("Cause exception while process update %s", 42)
    try:
        raise RuntimeError("handler blew up")
    except RuntimeError:
        logging.getLogger("arq.worker").exception("job failed")

    first, second = _lines(tmp_path / "bot.log")
    assert first["event"] == "Cause exception while process update 42"
    assert first["level"] == "error"
    assert first["logger"] == "aiogram.event"
    assert first["request_id"] == "r-2"
    assert "RuntimeError: handler blew up" in second["exception"]


@pytest.mark.usefixtures("restore_logging")
def test_file_rotates_by_size_and_keeps_n_backups(tmp_path: Path) -> None:
    configure_logging(service="bot", log_dir=tmp_path, log_file_max_bytes=400, log_file_backups=2)
    logger = get_logger("src.test")

    for i in range(100):
        logger.info("filler", i=i, padding="x" * 40)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["bot.log", "bot.log.1", "bot.log.2"]
    # The newest line is in the live file, nothing in it is truncated.
    assert _lines(tmp_path / "bot.log")[-1]["i"] == 99


@pytest.mark.usefixtures("restore_logging")
def test_reconfiguring_replaces_handlers_instead_of_stacking(tmp_path: Path) -> None:
    configure_logging(service="bot", log_dir=tmp_path)
    configure_logging(service="bot", log_dir=tmp_path)

    get_logger("src.test").info("once")

    assert len(_lines(tmp_path / "bot.log")) == 1
    owned = [h for h in logging.getLogger().handlers if getattr(h, "_umd_owned", False)]
    assert len(owned) == 2  # stdout + file


@pytest.mark.usefixtures("restore_logging")
def test_unusable_log_dir_falls_back_to_stdout_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")

    configure_logging(environment="production", service="bot", log_dir=blocker / "logs")
    get_logger("src.test").info("still_logging")

    out = capsys.readouterr().out
    assert "log_file_unavailable" in out
    assert "still_logging" in out


@pytest.mark.asyncio
async def test_bound_context_stays_inside_its_task() -> None:
    """Each arq job / aiogram update is its own task — the isolation the
    request_id tags rely on."""
    seen: dict[str, dict[str, Any]] = {}
    both_bound = asyncio.Event()
    count = 0

    async def unit(request_id: str) -> None:
        nonlocal count
        clear_log_context()
        bind_log_context(request_id=request_id)
        count += 1
        if count == 2:
            both_bound.set()
        await both_bound.wait()
        seen[request_id] = structlog.contextvars.get_contextvars()

    await asyncio.gather(unit("a"), unit("b"))

    assert seen == {"a": {"request_id": "a"}, "b": {"request_id": "b"}}
    assert "request_id" not in structlog.contextvars.get_contextvars()


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ValueError("bad value"), "bad value"),
        (ValueError("  padded\n"), "padded"),
        (ValueError(), "ValueError"),
        (ValueError("   "), "ValueError"),
        (KeyError(""), "''"),
    ],
)
def test_describe_error_never_logs_an_empty_string(exc: BaseException, expected: str) -> None:
    assert describe_error(exc) == expected
