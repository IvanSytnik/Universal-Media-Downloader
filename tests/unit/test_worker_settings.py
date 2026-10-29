"""WorkerSettings.max_jobs comes from Settings, not from arq's default."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

_MODULE = "src.infrastructure.queue.worker_settings"


def _fresh_worker_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ModuleType:
    # Settings are read at import time; run from an empty directory so a
    # developer's .env cannot leak in.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.delitem(sys.modules, _MODULE, raising=False)
    return importlib.import_module(_MODULE)


def test_max_jobs_defaults_to_four(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WORKER_MAX_JOBS", raising=False)
    assert _fresh_worker_settings(monkeypatch, tmp_path).WorkerSettings.max_jobs == 4


def test_max_jobs_follows_the_setting(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKER_MAX_JOBS", "2")
    assert _fresh_worker_settings(monkeypatch, tmp_path).WorkerSettings.max_jobs == 2
