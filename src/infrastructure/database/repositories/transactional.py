"""Repositories whose every call is its own committed transaction.

For the worker (ADR 0004). ``download_job`` used to run the whole use
case inside one ``session_scope``, i.e. one transaction for the entire
download — up to ``job_timeout``. That made PROCESSING invisible to
everyone else until the job ended, kept the row locked (a reaper UPDATE
would have waited half an hour on it) and held a pooled connection
idle-in-transaction the whole time; and if the worker died, the rollback
put the row back to PENDING with no trace that it had ever started.

The worker's writes are single-row status transitions with nothing to
make atomic together, so one transaction per call is the right unit:
each transition is visible and durable the moment it happens.

These wrap the session-bound repositories instead of duplicating them —
one mapping, two transaction policies.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.stale_request import StaleRequest
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository


class TransactionalDownloadRequestRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyDownloadRequestRepository(session).get_by_id(request_id)

    async def create(self, download_request: DownloadRequest) -> DownloadRequest:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyDownloadRequestRepository(session).create(download_request)

    async def update(self, download_request: DownloadRequest) -> None:
        async with session_scope(self._session_factory) as session:
            await SqlAlchemyDownloadRequestRepository(session).update(download_request)

    async def mark_failed_by_id(self, request_id: UUID) -> None:
        async with session_scope(self._session_factory) as session:
            await SqlAlchemyDownloadRequestRepository(session).mark_failed_by_id(request_id)

    async def claim_for_processing(self, request_id: UUID) -> bool:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyDownloadRequestRepository(session).claim_for_processing(
                request_id
            )

    async def fail_stale(self, updated_before: datetime, limit: int) -> list[StaleRequest]:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyDownloadRequestRepository(session).fail_stale(
                updated_before, limit
            )

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyDownloadRequestRepository(session).list_by_user(user_id, limit)


class TransactionalUserRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_by_id(self, user_id: UUID) -> User | None:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyUserRepository(session).get_by_id(user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyUserRepository(session).get_by_telegram_id(telegram_id)

    async def create(self, user: User) -> User:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyUserRepository(session).create(user)

    async def set_language(self, telegram_id: int, language: str | None) -> User | None:
        async with session_scope(self._session_factory) as session:
            return await SqlAlchemyUserRepository(session).set_language(telegram_id, language)
