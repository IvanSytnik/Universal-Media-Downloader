"""Migration 0006_updated_at and the reaper's locking, against a real
Postgres.

Same opt-in and scratch database as test_migration_0005.py
(``UMD_MIGRATION_TEST_PG=host:port``). Two things only Postgres can
show: the backfill/partial index of the migration itself, and that
``fail_stale`` SKIPS a row another transaction holds instead of waiting
on it (``FOR UPDATE SKIP LOCKED`` — SQLite ignores row locks).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)

asyncpg = pytest.importorskip("asyncpg")

_TARGET = os.environ.get("UMD_MIGRATION_TEST_PG")
pytestmark = pytest.mark.skipif(not _TARGET, reason="UMD_MIGRATION_TEST_PG not set")

_DB = "umd_migration_test"
_USER = os.environ.get("POSTGRES_USER", "umd")
_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "umd")
_ROOT = Path(__file__).resolve().parents[2]
_INDEX = "ix_download_requests_active_updated_at"


def _host_port() -> tuple[str, int]:
    assert _TARGET is not None
    host, _, port = _TARGET.rpartition(":")
    return host, int(port)


def _alembic(*args: str) -> None:
    host, port = _host_port()
    env = {
        **os.environ,
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": str(port),
        "POSTGRES_DB": _DB,
        "POSTGRES_USER": _USER,
        "POSTGRES_PASSWORD": _PASSWORD,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=_ROOT, env=env, check=True, timeout=120
    )


async def _connect(database: str) -> asyncpg.Connection:
    host, port = _host_port()
    return await asyncpg.connect(
        host=host, port=port, user=_USER, password=_PASSWORD, database=database
    )


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[asyncpg.Connection]:
    admin = await _connect("postgres")
    await admin.execute(f"DROP DATABASE IF EXISTS {_DB}")
    await admin.execute(f"CREATE DATABASE {_DB}")
    try:
        _alembic("upgrade", "0005_video_tier")
        conn = await _connect(_DB)
        try:
            yield conn
        finally:
            await conn.close()
    finally:
        await admin.execute(f"DROP DATABASE IF EXISTS {_DB}")
        await admin.close()


async def _insert(
    conn: asyncpg.Connection,
    user_id: object,
    status: str,
    created_at: datetime,
    completed_at: datetime | None = None,
) -> object:
    request_id = uuid4()
    await conn.execute(
        "INSERT INTO download_requests "
        "(id, user_id, source_url, status, format_kind, video_tier, created_at, completed_at) "
        "VALUES ($1, $2, 'https://example.com/v', $3, 'video', 'p720', $4, $5)",
        request_id,
        user_id,
        status,
        created_at,
        completed_at,
    )
    return request_id


@pytest.mark.asyncio
async def test_0006_backfills_updated_at_and_downgrade_drops_it(db: asyncpg.Connection) -> None:
    user_id = uuid4()
    await db.execute("INSERT INTO users (id, telegram_id) VALUES ($1, 1)", user_id)
    created = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    completed = created + timedelta(minutes=5)
    pending = await _insert(db, user_id, "pending", created)
    done = await _insert(db, user_id, "done", created, completed)

    _alembic("upgrade", "0006_updated_at")

    rows = {
        r["id"]: r["updated_at"]
        for r in await db.fetch("SELECT id, updated_at FROM download_requests")
    }
    assert rows == {pending: created, done: completed}
    nullable = await db.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'download_requests' AND column_name = 'updated_at'"
    )
    assert nullable == "NO"
    index_def: str = await db.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = $1", _INDEX
    )
    assert "WHERE" in index_def and "pending" in index_def and "processing" in index_def
    # The server default covers inserts written without the column.
    fresh = await _insert(db, user_id, "pending", created)
    assert await db.fetchval("SELECT updated_at FROM download_requests WHERE id = $1", fresh)

    _alembic("downgrade", "0005_video_tier")

    columns = {
        r["column_name"]
        for r in await db.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'download_requests'"
        )
    }
    assert "updated_at" not in columns
    assert await db.fetchval("SELECT 1 FROM pg_indexes WHERE indexname = $1", _INDEX) is None


@pytest_asyncio.fixture
async def session_factory(
    db: asyncpg.Connection,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    _alembic("upgrade", "head")
    host, port = _host_port()
    engine = create_async_engine(f"postgresql+asyncpg://{_USER}:{_PASSWORD}@{host}:{port}/{_DB}")
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_reaper_skips_a_row_a_live_transaction_holds(
    db: asyncpg.Connection, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = uuid4()
    await db.execute("INSERT INTO users (id, telegram_id) VALUES ($1, 1)", user_id)
    old = datetime.now(UTC) - timedelta(hours=2)
    request_id = await _insert(db, user_id, "pending", old)
    await db.execute("UPDATE download_requests SET updated_at = $1 WHERE id = $2", old, request_id)
    far_future = datetime.now(UTC) + timedelta(days=1)

    async with session_factory() as job, session_factory() as reaper:
        # A job mid-claim: the row is locked, not yet committed.
        assert await SqlAlchemyDownloadRequestRepository(job).claim_for_processing(request_id)

        # Must come back at once with nothing, not wait for the job.
        skipped = await asyncio.wait_for(
            SqlAlchemyDownloadRequestRepository(reaper).fail_stale(far_future, 100), timeout=5
        )
        assert skipped == []
        await reaper.rollback()

        await job.commit()

    # Committed claim: the clock was reset, so a realistic cutoff skips it...
    async with session_factory() as reaper:
        repo = SqlAlchemyDownloadRequestRepository(reaper)
        assert await repo.fail_stale(datetime.now(UTC) - timedelta(minutes=40), 100) == []
        # ...and once it is genuinely silent, it is reaped exactly once.
        assert [r.request_id for r in await repo.fail_stale(far_future, 100)] == [request_id]
        await reaper.commit()
        assert await repo.fail_stale(far_future, 100) == []

    assert (
        await db.fetchval("SELECT status FROM download_requests WHERE id = $1", request_id)
        == "failed"
    )
