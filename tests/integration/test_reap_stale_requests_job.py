"""The cron job end to end on SQLite: real transactional repositories,
real FTL, fake Telegram — plus the worker's cron registration.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.enums import DownloadStatus
from src.infrastructure.database.engine import Base
from src.infrastructure.database.models import DownloadRequestModel
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.infrastructure.queue.jobs import reap_stale_requests_job
from tests.conftest import FakeErrorLocalizer


class _Notifier:
    def __init__(self) -> None:
        self.sent_texts: list[tuple[int, str]] = []

    async def send_text(self, telegram_id: int, text: str) -> None:
        self.sent_texts.append((telegram_id, text))


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'job.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_job_fails_stale_requests_and_notifies_once(
    session_factory: async_sessionmaker[AsyncSession], i18n_core: Any
) -> None:
    async with session_factory() as session:
        user = await SqlAlchemyUserRepository(session).create(
            User.create_from_telegram(telegram_id=77, language="ru")
        )
        stale = DownloadRequest.create(user_id=user.id, source_url="https://example.com/a")
        fresh = DownloadRequest.create(user_id=user.id, source_url="https://example.com/b")
        repo = SqlAlchemyDownloadRequestRepository(session)
        await repo.create(stale)
        await repo.create(fresh)
        model = await session.get(DownloadRequestModel, stale.id)
        assert model is not None
        model.status = DownloadStatus.PROCESSING
        model.updated_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    notifier = _Notifier()
    localizer = FakeErrorLocalizer(i18n_core)
    ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "notifier": notifier,
        "error_localizer": localizer,
        "stale_request_after": timedelta(seconds=2400),
    }

    assert await reap_stale_requests_job(ctx) == 1
    assert await reap_stale_requests_job(ctx) == 0

    assert notifier.sent_texts == [(77, localizer.localize("error-request-stale", "ru"))]
    async with session_factory() as session:
        repo = SqlAlchemyDownloadRequestRepository(session)
        reaped = await repo.get_by_id(stale.id)
        untouched = await repo.get_by_id(fresh.id)
    assert reaped is not None and reaped.status == DownloadStatus.FAILED
    assert untouched is not None and untouched.status == DownloadStatus.PENDING


def test_worker_runs_the_reaper_on_cron(monkeypatch: pytest.MonkeyPatch) -> None:
    # worker_settings reads Settings at import; CI has no .env.
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    monkeypatch.delitem(sys.modules, "src.infrastructure.queue.worker_settings", raising=False)
    worker_settings = importlib.import_module("src.infrastructure.queue.worker_settings")

    crons = {job.coroutine: job for job in worker_settings.WorkerSettings.cron_jobs}
    assert reap_stale_requests_job in crons
    assert crons[reap_stale_requests_job].minute == set(range(0, 60, 5))
    # The reaper's threshold is derived from the same constant arq enforces.
    assert worker_settings.WorkerSettings.job_timeout == worker_settings.JOB_TIMEOUT_SECONDS
