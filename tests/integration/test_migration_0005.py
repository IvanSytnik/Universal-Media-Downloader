"""Migration 0005_video_tier against a real Postgres, with data.

Lesson 11A.0: a migration is only verified by running it. This test
seeds rows at revision 0004, upgrades, checks the backfill and that the
CHECK rejects a mismatched pair, then downgrades and checks the (lossy)
restore of quality_kind.

Opt-in: set ``UMD_MIGRATION_TEST_PG=host:port`` (e.g. the compose
postgres, ``127.0.0.1:5433``). Credentials come from POSTGRES_USER /
POSTGRES_PASSWORD (default umd/umd). The test creates and drops its own
scratch database, ``umd_migration_test`` — it never touches the app DB.
Alembic runs in a subprocess so env.py reads Settings fresh, exactly as
``alembic upgrade`` does in the container.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

asyncpg = pytest.importorskip("asyncpg")

_TARGET = os.environ.get("UMD_MIGRATION_TEST_PG")
pytestmark = pytest.mark.skipif(not _TARGET, reason="UMD_MIGRATION_TEST_PG not set")

_DB = "umd_migration_test"
_USER = os.environ.get("POSTGRES_USER", "umd")
_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "umd")
_ROOT = Path(__file__).resolve().parents[2]


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
        _alembic("upgrade", "0004_quality_kind")
        conn = await _connect(_DB)
        try:
            yield conn
        finally:
            await conn.close()
    finally:
        await admin.execute(f"DROP DATABASE IF EXISTS {_DB}")
        await admin.close()


async def _format_kind_default(conn: asyncpg.Connection) -> str | None:
    default: str | None = await conn.fetchval(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'download_requests' AND column_name = 'format_kind'"
    )
    return default


async def _columns(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'download_requests'"
    )
    return {r["column_name"] for r in rows}


async def _insert(conn: asyncpg.Connection, user_id: object, **columns: str | None) -> object:
    request_id = uuid4()
    names = ["id", "user_id", "source_url", *columns]
    values = [request_id, user_id, "https://example.com/v", *columns.values()]
    placeholders = ", ".join(f"${i}" for i in range(1, len(values) + 1))
    await conn.execute(
        f"INSERT INTO download_requests ({', '.join(names)}) VALUES ({placeholders})", *values
    )
    return request_id


@pytest.mark.asyncio
async def test_0005_upgrade_backfills_and_downgrade_restores(db: asyncpg.Connection) -> None:
    user_id = uuid4()
    await db.execute("INSERT INTO users (id, telegram_id) VALUES ($1, 1)", user_id)
    v720 = await _insert(db, user_id, format_kind="video", quality_kind="hd_720")
    v1080 = await _insert(db, user_id, format_kind="video", quality_kind="hd_1080")
    audio = await _insert(db, user_id, format_kind="audio", quality_kind="hd_720")
    # Audio rows carried a placeholder tier; even a non-default one must
    # not leak into video_tier.
    audio_1080 = await _insert(db, user_id, format_kind="audio", quality_kind="hd_1080")

    _alembic("upgrade", "0005_video_tier")

    assert await db.fetchval("SELECT version_num FROM alembic_version") == "0005_video_tier"
    columns = await _columns(db)
    assert "video_tier" in columns
    assert "quality_kind" not in columns
    # Both halves of the pair are app-written: no default on either.
    assert await _format_kind_default(db) is None
    tiers = {
        r["id"]: r["video_tier"]
        for r in await db.fetch("SELECT id, video_tier FROM download_requests")
    }
    assert tiers == {v720: "p720", v1080: "p1080", audio: None, audio_1080: None}

    for kind, tier in (("video", None), ("audio", "p720")):
        with pytest.raises(asyncpg.CheckViolationError) as caught:
            await _insert(db, user_id, format_kind=kind, video_tier=tier)
        assert caught.value.constraint_name == "ck_download_requests_video_tier_kind"

    best = await _insert(db, user_id, format_kind="video", video_tier="best")

    _alembic("downgrade", "0004_quality_kind")

    columns = await _columns(db)
    assert "quality_kind" in columns
    assert "video_tier" not in columns
    assert await _format_kind_default(db) == "'video'::character varying"
    restored = {
        r["id"]: r["quality_kind"]
        for r in await db.fetch("SELECT id, quality_kind FROM download_requests")
    }
    # Lossy by design: only p1080 survives as hd_1080; best → hd_720.
    assert restored == {
        v720: "hd_720",
        v1080: "hd_1080",
        audio: "hd_720",
        audio_1080: "hd_720",
        best: "hd_720",
    }
    constraints = await db.fetch(
        "SELECT conname FROM pg_constraint WHERE conname = 'ck_download_requests_video_tier_kind'"
    )
    assert constraints == []
