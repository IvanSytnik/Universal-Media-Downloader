"""Repository integration tests against an in-memory SQLite database.

Note: this is NOT a substitute for testing against real PostgreSQL —
it's a fast local check that the ORM mapping and repository logic
are self-consistent (create → read gives back the same data). Postgres-
specific behavior (e.g. exact server_default semantics) is only verified
when running via `docker compose up` with the real database, per
PROJECT_SPEC §7: "infrastructure — integration tests through testcontainers
(Postgres, Redis)". Testcontainers-based Postgres tests are a Day 3+ CI
improvement once the project has a CI runner with Docker-in-Docker
available — tracked, not skipped silently.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
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


@pytest.mark.asyncio
async def test_user_repository_create_and_get(session: AsyncSession) -> None:
    repo = SqlAlchemyUserRepository(session)
    user = User.create_from_telegram(telegram_id=42)

    created = await repo.create(user)
    await session.commit()

    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.telegram_id == 42

    by_telegram_id = await repo.get_by_telegram_id(42)
    assert by_telegram_id is not None
    assert by_telegram_id.id == created.id


@pytest.mark.asyncio
async def test_user_repository_returns_none_for_unknown_telegram_id(
    session: AsyncSession,
) -> None:
    repo = SqlAlchemyUserRepository(session)
    assert await repo.get_by_telegram_id(999999) is None


@pytest.mark.asyncio
async def test_download_request_repository_create_and_list(session: AsyncSession) -> None:
    user_repo = SqlAlchemyUserRepository(session)
    user = await user_repo.create(User.create_from_telegram(telegram_id=1))
    await session.flush()

    request_repo = SqlAlchemyDownloadRequestRepository(session)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")
    await request_repo.create(request)
    await session.commit()

    fetched = await request_repo.get_by_id(request.id)
    assert fetched is not None
    assert fetched.source_url == "https://example.com/video"

    listed = await request_repo.list_by_user(user.id)
    assert len(listed) == 1
    assert listed[0].id == request.id
