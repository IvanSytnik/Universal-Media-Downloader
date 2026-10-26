"""Reaper-side repository behaviour against SQLite: ``updated_at``
stamping, the ``claim_for_processing`` / ``fail_stale`` compare-and-sets,
their boundaries, and idempotency.

Row locking (``FOR UPDATE SKIP LOCKED``) is Postgres-only and is pinned
in test_migration_0006.py; here the WHERE re-check alone carries the
guarantees, which is also what the Postgres path falls back on.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.enums import DownloadStatus
from src.domain.value_objects.stale_request import StaleRequest
from src.infrastructure.database.engine import Base
from src.infrastructure.database.models import DownloadRequestModel
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.transactional import (
    TransactionalDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository

_NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    # A file, not :memory: — the transactional repository opens a new
    # connection per call, and every :memory: connection is its own DB.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reaper.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def user(session: AsyncSession) -> User:
    created = await SqlAlchemyUserRepository(session).create(
        User.create_from_telegram(telegram_id=42)
    )
    await session.commit()
    return created


async def _seed(
    session: AsyncSession,
    user: User,
    status: DownloadStatus,
    updated_at: datetime,
) -> UUID:
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v")
    await SqlAlchemyDownloadRequestRepository(session).create(request)
    model = await session.get(DownloadRequestModel, request.id)
    assert model is not None
    model.status = status
    model.updated_at = updated_at
    if status in (DownloadStatus.DONE, DownloadStatus.FAILED):
        model.completed_at = updated_at
    await session.commit()
    return request.id


async def _row(session: AsyncSession, request_id: UUID) -> DownloadRequestModel:
    session.expire_all()
    model = (
        await session.execute(
            select(DownloadRequestModel).where(DownloadRequestModel.id == request_id)
        )
    ).scalar_one()
    return model


def _naive(value: datetime) -> datetime:
    # SQLite hands timestamps back without tzinfo.
    return value.replace(tzinfo=None)


# --- updated_at stamping ---------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_update_stamp_updated_at(session: AsyncSession, user: User) -> None:
    repo = SqlAlchemyDownloadRequestRepository(session)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v")
    before = datetime.now(UTC)
    await repo.create(request)
    await session.commit()
    created_at = (await _row(session, request.id)).updated_at
    assert _naive(created_at) >= _naive(before)

    request.mark_done()
    await repo.update(request)
    await session.commit()

    assert (await _row(session, request.id)).updated_at > created_at


@pytest.mark.asyncio
async def test_mark_failed_by_id_stamps_updated_at(session: AsyncSession, user: User) -> None:
    request_id = await _seed(session, user, DownloadStatus.PENDING, _NOW - timedelta(days=1))

    await SqlAlchemyDownloadRequestRepository(session).mark_failed_by_id(request_id)
    await session.commit()

    assert _naive((await _row(session, request_id)).updated_at) > _naive(_NOW - timedelta(days=1))


# --- claim_for_processing --------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DownloadStatus.PENDING, DownloadStatus.PROCESSING])
async def test_claim_takes_active_request_and_refreshes_updated_at(
    session: AsyncSession, user: User, status: DownloadStatus
) -> None:
    old = _NOW - timedelta(hours=2)
    request_id = await _seed(session, user, status, old)

    claimed = await SqlAlchemyDownloadRequestRepository(session).claim_for_processing(request_id)
    await session.commit()

    assert claimed is True
    row = await _row(session, request_id)
    assert row.status == DownloadStatus.PROCESSING
    # PROCESSING → PROCESSING (an arq retry) changes no status, and must
    # still move the reaper's clock — the reason updated_at is not an
    # ORM onupdate.
    assert _naive(row.updated_at) > _naive(old)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [DownloadStatus.DONE, DownloadStatus.FAILED])
async def test_claim_refuses_finished_request(
    session: AsyncSession, user: User, status: DownloadStatus
) -> None:
    request_id = await _seed(session, user, status, _NOW)

    claimed = await SqlAlchemyDownloadRequestRepository(session).claim_for_processing(request_id)

    assert claimed is False
    row = await _row(session, request_id)
    assert row.status == status
    assert _naive(row.updated_at) == _naive(_NOW)


@pytest.mark.asyncio
async def test_claim_of_unknown_request_is_false(session: AsyncSession) -> None:
    assert await SqlAlchemyDownloadRequestRepository(session).claim_for_processing(uuid4()) is False


# --- fail_stale -------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_stale_fails_only_old_active_requests(session: AsyncSession, user: User) -> None:
    cutoff = _NOW - timedelta(minutes=40)
    old = cutoff - timedelta(minutes=1)
    stale_pending = await _seed(session, user, DownloadStatus.PENDING, old)
    stale_processing = await _seed(session, user, DownloadStatus.PROCESSING, old)
    fresh_processing = await _seed(session, user, DownloadStatus.PROCESSING, _NOW)
    old_done = await _seed(session, user, DownloadStatus.DONE, old)
    old_failed = await _seed(session, user, DownloadStatus.FAILED, old)
    repo = SqlAlchemyDownloadRequestRepository(session)

    reaped = await repo.fail_stale(cutoff, limit=100)
    await session.commit()

    assert sorted(reaped, key=lambda r: r.previous_status) == [
        StaleRequest(stale_pending, user.id, DownloadStatus.PENDING),
        StaleRequest(stale_processing, user.id, DownloadStatus.PROCESSING),
    ]
    for request_id in (stale_pending, stale_processing):
        row = await _row(session, request_id)
        assert row.status == DownloadStatus.FAILED
        assert row.completed_at is not None
        assert _naive(row.updated_at) > _naive(old)
    assert (await _row(session, fresh_processing)).status == DownloadStatus.PROCESSING
    assert (await _row(session, old_done)).status == DownloadStatus.DONE
    assert (await _row(session, old_failed)).status == DownloadStatus.FAILED


@pytest.mark.asyncio
async def test_fail_stale_boundary_is_strict(session: AsyncSession, user: User) -> None:
    cutoff = _NOW - timedelta(minutes=40)
    at_cutoff = await _seed(session, user, DownloadStatus.PROCESSING, cutoff)
    just_before = await _seed(
        session, user, DownloadStatus.PROCESSING, cutoff - timedelta(microseconds=1)
    )

    reaped = await SqlAlchemyDownloadRequestRepository(session).fail_stale(cutoff, limit=100)

    assert [r.request_id for r in reaped] == [just_before]
    assert (await _row(session, at_cutoff)).status == DownloadStatus.PROCESSING


@pytest.mark.asyncio
async def test_fail_stale_takes_oldest_first_and_drains_over_batches(
    session: AsyncSession, user: User
) -> None:
    cutoff = _NOW
    oldest = await _seed(session, user, DownloadStatus.PENDING, _NOW - timedelta(hours=3))
    middle = await _seed(session, user, DownloadStatus.PENDING, _NOW - timedelta(hours=2))
    newest = await _seed(session, user, DownloadStatus.PENDING, _NOW - timedelta(hours=1))
    repo = SqlAlchemyDownloadRequestRepository(session)

    first = await repo.fail_stale(cutoff, limit=2)
    await session.commit()
    second = await repo.fail_stale(cutoff, limit=2)
    await session.commit()
    third = await repo.fail_stale(cutoff, limit=2)

    assert [r.request_id for r in first] == [oldest, middle]
    assert [r.request_id for r in second] == [newest]
    assert third == []


@pytest.mark.asyncio
async def test_fail_stale_is_idempotent(session: AsyncSession, user: User) -> None:
    request_id = await _seed(session, user, DownloadStatus.PROCESSING, _NOW - timedelta(hours=1))
    repo = SqlAlchemyDownloadRequestRepository(session)

    assert len(await repo.fail_stale(_NOW, limit=100)) == 1
    await session.commit()
    first_completed_at = (await _row(session, request_id)).completed_at

    # Same cutoff again — the row is FAILED now and must not come back.
    assert await repo.fail_stale(_NOW, limit=100) == []
    assert (await _row(session, request_id)).completed_at == first_completed_at


@pytest.mark.asyncio
async def test_reaped_request_cannot_be_claimed_by_a_late_retry(
    session: AsyncSession, user: User
) -> None:
    request_id = await _seed(session, user, DownloadStatus.PROCESSING, _NOW - timedelta(hours=1))
    repo = SqlAlchemyDownloadRequestRepository(session)
    await repo.fail_stale(_NOW, limit=100)
    await session.commit()

    assert await repo.claim_for_processing(request_id) is False
    assert (await _row(session, request_id)).status == DownloadStatus.FAILED


@pytest.mark.asyncio
async def test_fresh_claim_protects_request_from_the_reaper(
    session: AsyncSession, user: User
) -> None:
    request_id = await _seed(session, user, DownloadStatus.PENDING, _NOW - timedelta(hours=1))
    repo = SqlAlchemyDownloadRequestRepository(session)
    assert await repo.claim_for_processing(request_id) is True
    await session.commit()

    # Cutoff computed for "an hour of silence": the claim just reset the clock.
    reaped = await repo.fail_stale(datetime.now(UTC) - timedelta(minutes=40), limit=100)

    assert reaped == []
    assert (await _row(session, request_id)).status == DownloadStatus.PROCESSING


@pytest.mark.asyncio
async def test_fail_stale_ignores_rows_with_unreadable_status(
    session: AsyncSession, user: User
) -> None:
    request_id = await _seed(session, user, DownloadStatus.PENDING, _NOW - timedelta(hours=1))
    model = await session.get(DownloadRequestModel, request_id)
    assert model is not None
    model.status = "archived"  # type: ignore[assignment]  # a value this build doesn't know
    await session.commit()

    assert await SqlAlchemyDownloadRequestRepository(session).fail_stale(_NOW, limit=100) == []


# --- transaction per call ---------------------------------------------------


@pytest.mark.asyncio
async def test_transactional_claim_is_committed_and_visible_to_other_sessions(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession, user: User
) -> None:
    request_id = await _seed(session, user, DownloadStatus.PENDING, _NOW)

    assert await TransactionalDownloadRequestRepository(session_factory).claim_for_processing(
        request_id
    )

    # Read from an unrelated session: the claim did not wait for the job to end.
    async with session_factory() as other:
        row = await other.get(DownloadRequestModel, request_id)
        assert row is not None
        assert row.status == DownloadStatus.PROCESSING
