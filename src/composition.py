"""Composition root for the bot process: concrete adapters → use cases.

This is the one place in the bot process that may import from every
layer. ``src/main.py`` builds the long-lived resources (engine, Redis,
arq pool) and hands them to ``SqlAlchemyUseCaseProvider``, which the
dispatcher injects into handlers as ``use_cases``. Presentation sees only
the ``UseCaseProvider`` protocol, never this module.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.policies.format_policy import FormatPolicy
from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.application.use_cases.register_user import RegisterUserUseCase
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.application.use_cases.set_user_language import SetUserLanguageUseCase
from src.application.use_cases.trigger_ping_job import TriggerPingJobUseCase
from src.domain.interfaces.downloader import DownloaderPort
from src.domain.interfaces.task_queue import TaskQueue
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.presentation.telegram.dependencies import UseCaseProvider


class SqlAlchemyUseCaseProvider(UseCaseProvider):
    """Builds use cases over SQLAlchemy repositories, one session per
    ``async with``. Stateless adapters (downloader, task queue) are shared
    across requests."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        task_queue: TaskQueue,
        downloader: DownloaderPort,
        format_policy: FormatPolicy,
    ) -> None:
        self._session_factory = session_factory
        self._task_queue = task_queue
        self._downloader = downloader
        self._format_policy = format_policy

    @asynccontextmanager
    async def register_user(self) -> AsyncIterator[RegisterUserUseCase]:
        async with session_scope(self._session_factory) as session:
            yield RegisterUserUseCase(SqlAlchemyUserRepository(session))

    @asynccontextmanager
    async def request_download(self) -> AsyncIterator[RequestDownloadUseCase]:
        async with session_scope(self._session_factory) as session:
            yield RequestDownloadUseCase(
                user_repository=SqlAlchemyUserRepository(session),
                download_request_repository=SqlAlchemyDownloadRequestRepository(session),
                task_queue=self._task_queue,
                format_policy=self._format_policy,
            )

    @asynccontextmanager
    async def set_user_language(self) -> AsyncIterator[SetUserLanguageUseCase]:
        async with session_scope(self._session_factory) as session:
            yield SetUserLanguageUseCase(SqlAlchemyUserRepository(session))

    def preview_download(self) -> PreviewDownloadUseCase:
        return PreviewDownloadUseCase(self._downloader)

    def trigger_ping_job(self) -> TriggerPingJobUseCase:
        return TriggerPingJobUseCase(self._task_queue)
