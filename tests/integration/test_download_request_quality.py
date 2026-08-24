"""Day 11C stage 2: quality_kind survives the trip through the repository.

Against in-memory SQLite (same caveat as test_repositories.py: this
checks ORM mapping + repository logic, not Postgres server_default
semantics — that is verified by the live `alembic upgrade head` run).

The second test is the guard that matters: ``update`` is called on every
state transition and must not silently reset quality_kind, which is the
shape of bug 11A.1 (a field persisted on create but lost downstream).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.quality_kind import QualityKind
from src.infrastructure.database.engine import Base
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s

    await engine.dispose()


async def _make_user(session: AsyncSession) -> User:
    user = await SqlAlchemyUserRepository(session).create(User.create_from_telegram(telegram_id=1))
    await session.flush()
    return user


@pytest.mark.parametrize("quality", [QualityKind.HD_720, QualityKind.HD_1080])
@pytest.mark.asyncio
async def test_quality_kind_roundtrips(session: AsyncSession, quality: QualityKind) -> None:
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    request = DownloadRequest.create(
        user_id=user.id, source_url="https://example.com/v", quality_kind=quality
    )
    await repo.create(request)
    await session.commit()

    fetched = await repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.quality_kind is quality


@pytest.mark.asyncio
async def test_default_quality_is_persisted(session: AsyncSession) -> None:
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v")
    await repo.create(request)
    await session.commit()

    fetched = await repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.quality_kind is QualityKind.HD_720


@pytest.mark.asyncio
async def test_update_does_not_clobber_quality_kind(session: AsyncSession) -> None:
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    request = DownloadRequest.create(
        user_id=user.id,
        source_url="https://example.com/v",
        quality_kind=QualityKind.HD_1080,
    )
    await repo.create(request)
    await session.commit()

    request.mark_processing()
    await repo.update(request)
    request.mark_done()
    await repo.update(request)
    await session.commit()

    fetched = await repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.quality_kind is QualityKind.HD_1080


@pytest.mark.asyncio
async def test_listing_skips_a_corrupted_row_instead_of_dying(session: AsyncSession) -> None:
    """Day 11C stage 5: one unreadable row must not hide a user's whole
    history.

    ``get_by_id`` raises CorruptedRecordError — right, because that one
    request genuinely cannot be processed. A LISTING is a set of
    independent rows, so the same exception there would turn one bad row
    into "all your downloads vanished". It skips instead, and says so in
    the log (a silently shorter list is undebuggable).
    """
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    good = DownloadRequest.create(user_id=user.id, source_url="https://example.com/good")
    bad = DownloadRequest.create(user_id=user.id, source_url="https://example.com/bad")
    await repo.create(good)
    await repo.create(bad)
    await session.commit()

    # Corrupt one row the way only a foreign writer or a rollback could:
    # the column is a plain varchar with no CHECK constraint.
    await session.execute(
        text("update download_requests set status = 'garbage' where id = :id"),
        {"id": bad.id.hex},
    )
    await session.commit()
    session.expire_all()

    with structlog.testing.capture_logs() as logs:
        listed = await repo.list_by_user(user.id)

    assert [r.id for r in listed] == [good.id]
    entry = [e for e in logs if e["event"] == "download_request_skipped_in_listing"][0]
    assert entry["log_level"] == "error"
    assert entry["request_id"] == str(bad.id)
    assert entry["raw_value"] == "garbage"
