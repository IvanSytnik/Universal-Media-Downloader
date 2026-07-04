"""Async SQLAlchemy engine and session factory.

Single place that owns the connection pool. Both the bot process and,
from Day 3, the worker process import `create_session_factory` — they
each create their own engine (never share one across processes).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.config.settings import Settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.sqlalchemy_dsn, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession]:
    """Commit on success, rollback on exception. One session per unit of work."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
