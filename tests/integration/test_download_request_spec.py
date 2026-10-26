"""Day 11C: the request's DownloadSpec survives the trip through the
repository (stored as ``format_kind`` + ``video_tier``).

Against in-memory SQLite (same caveat as test_repositories.py: this
checks ORM mapping + repository logic, not Postgres server_default
semantics — that is verified by the live `alembic upgrade head` run).

The second test is the guard that matters: ``update`` is called on every
state transition and must not silently reset the spec, which is the
shape of bug 11A.1 (a field persisted on create but lost downstream).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)
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


_ALL_SPECS = [
    VideoSpec(VideoTier.P720),
    VideoSpec(VideoTier.P1080),
    VideoSpec(VideoTier.BEST),
    AudioSpec(),
]


@pytest.mark.parametrize("spec", _ALL_SPECS)
@pytest.mark.asyncio
async def test_spec_roundtrips(session: AsyncSession, spec: DownloadSpec) -> None:
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v", spec=spec)
    await repo.create(request)
    await session.commit()
    session.expire_all()

    fetched = await repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.spec == spec


@pytest.mark.parametrize(
    ("spec", "format_kind", "video_tier"),
    [
        (VideoSpec(VideoTier.P720), "video", "p720"),
        (VideoSpec(VideoTier.P1080), "video", "p1080"),
        (VideoSpec(VideoTier.BEST), "video", "best"),
        (AudioSpec(), "audio", None),
    ],
)
@pytest.mark.asyncio
async def test_spec_is_stored_as_explicit_columns(
    session: AsyncSession, spec: DownloadSpec, format_kind: str, video_tier: str | None
) -> None:
    # The raw columns are the contract with migration 0005 and its CHECK;
    # asserting only the roundtrip would pass with any private encoding.
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v", spec=spec)
    await repo.create(request)
    await session.commit()

    row = (
        await session.execute(
            text("select format_kind, video_tier from download_requests where id = :id"),
            {"id": request.id.hex},
        )
    ).one()
    assert tuple(row) == (format_kind, video_tier)


@pytest.mark.asyncio
async def test_default_spec_is_persisted(session: AsyncSession) -> None:
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v")
    await repo.create(request)
    await session.commit()

    fetched = await repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.spec == DEFAULT_DOWNLOAD_SPEC


@pytest.mark.parametrize("spec", [VideoSpec(VideoTier.P1080), AudioSpec()])
@pytest.mark.asyncio
async def test_update_does_not_clobber_spec(session: AsyncSession, spec: DownloadSpec) -> None:
    user = await _make_user(session)
    repo = SqlAlchemyDownloadRequestRepository(session)

    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/v", spec=spec)
    await repo.create(request)
    await session.commit()

    request.mark_processing()
    await repo.update(request)
    request.mark_done()
    await repo.update(request)
    await session.commit()
    session.expire_all()

    fetched = await repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.spec == spec


@pytest.mark.parametrize(("format_kind", "video_tier"), [("video", None), ("audio", "p720")])
@pytest.mark.asyncio
async def test_check_constraint_rejects_mismatched_pair(
    session: AsyncSession, format_kind: str, video_tier: str | None
) -> None:
    # The ORM model carries the same CHECK as migration 0005, so even
    # SQLite enforces it; the Postgres side is covered by the migration
    # test.
    user = await _make_user(session)
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "insert into download_requests "
                "(id, user_id, source_url, media_type, status, format_kind, video_tier) "
                "values (:id, :uid, 'https://x.y', 'video', 'pending', :fk, :vt)"
            ),
            {"id": uuid4().hex, "uid": user.id.hex, "fk": format_kind, "vt": video_tier},
        )


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
    # status is a plain varchar with no CHECK constraint.
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
