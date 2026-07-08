"""Day 9: users.language round-trips through the SQLAlchemy repository."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.domain.entities.user import User
from src.infrastructure.database.engine import Base
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_language_persists_and_reads_back(session_factory) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        created = await repo.create(User.create_from_telegram(111, language="ru"))
        await session.commit()
        fetched = await repo.get_by_telegram_id(111)
        assert fetched is not None
        assert fetched.language == "ru"
        assert fetched.id == created.id


@pytest.mark.asyncio
async def test_language_nullable_defaults_to_none(session_factory) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.create(User.create_from_telegram(222))
        await session.commit()
        fetched = await repo.get_by_telegram_id(222)
        assert fetched is not None
        assert fetched.language is None


@pytest.mark.asyncio
async def test_set_language_updates_existing_user(session_factory) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.create(User.create_from_telegram(333))
        await session.commit()
        updated = await repo.set_language(333, "en")
        await session.commit()
        assert updated is not None
        assert updated.language == "en"
        fetched = await repo.get_by_telegram_id(333)
        assert fetched is not None and fetched.language == "en"


@pytest.mark.asyncio
async def test_set_language_returns_none_for_unknown_user(session_factory) -> None:
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        assert await repo.set_language(999, "ru") is None
