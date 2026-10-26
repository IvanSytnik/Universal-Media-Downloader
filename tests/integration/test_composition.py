"""The composition root's use-case provider, against a real (SQLite) database.

The provider replaced per-handler ``session_scope`` blocks, so what must
hold is the same transaction boundary: one ``async with`` is one unit of
work, committed on success and rolled back on an exception.

Except ``request_download``, which commits per call so the request row
exists before its job does. The tests at the bottom pin that with a
queue that looks the row up from its own connection at enqueue time, the
way a worker would. They need a file database: ``:memory:`` hands every
session the same connection, which would see uncommitted rows and hide
the race. Against the old single-transaction provider both fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.application.policies.format_policy import FormatPolicy
from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.application.use_cases.trigger_ping_job import TriggerPingJobUseCase
from src.composition import SqlAlchemyUseCaseProvider
from src.domain.entities.download_request import DownloadRequest
from src.domain.exceptions import DownloadEnqueueError
from src.domain.value_objects.download_spec import AudioSpec
from src.domain.value_objects.enums import DownloadStatus
from src.infrastructure.database.engine import Base
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository


class _FakeTaskQueue:
    def __init__(self) -> None:
        self.downloads: list[tuple[UUID, int, int]] = []
        self.pings: list[str] = []

    async def enqueue_ping(self, message: str) -> str:
        self.pings.append(message)
        return "job-ping"

    async def enqueue_download(self, request_id: UUID, chat_id: int, message_id: int) -> str:
        self.downloads.append((request_id, chat_id, message_id))
        return "job-download"


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def task_queue() -> _FakeTaskQueue:
    return _FakeTaskQueue()


@pytest.fixture
def provider(session_factory: Any, task_queue: _FakeTaskQueue) -> SqlAlchemyUseCaseProvider:
    return SqlAlchemyUseCaseProvider(
        session_factory=session_factory,
        task_queue=task_queue,
        downloader=object(),  # type: ignore[arg-type]  # never called here
        format_policy=FormatPolicy({}),
    )


async def _user_language(session_factory: Any, telegram_id: int) -> str | None:
    async with session_factory() as session:
        user = await SqlAlchemyUserRepository(session).get_by_telegram_id(telegram_id)
        assert user is not None
        return user.language


@pytest.mark.asyncio
async def test_register_then_set_language_commits_each_unit_of_work(
    provider: SqlAlchemyUseCaseProvider, session_factory: Any
) -> None:
    async with provider.register_user() as register:
        await register.execute(100, language="en")
    async with provider.set_user_language() as set_language:
        await set_language.execute(100, "ru")

    # Read through a fresh session: only committed data is visible.
    assert await _user_language(session_factory, 100) == "ru"


@pytest.mark.asyncio
async def test_exception_inside_unit_of_work_rolls_back(
    provider: SqlAlchemyUseCaseProvider, session_factory: Any
) -> None:
    async with provider.register_user() as register:
        await register.execute(200, language="en")

    with pytest.raises(RuntimeError):
        async with provider.set_user_language() as set_language:
            await set_language.execute(200, "ru")
            raise RuntimeError("handler failed after the write")

    assert await _user_language(session_factory, 200) == "en"


@pytest.mark.asyncio
async def test_request_download_persists_and_enqueues(
    provider: SqlAlchemyUseCaseProvider, session_factory: Any, task_queue: _FakeTaskQueue
) -> None:
    async with provider.register_user() as register:
        await register.execute(300)

    async with provider.request_download() as request_download:
        request: DownloadRequest = await request_download.execute(
            300,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            AudioSpec(),
            "youtube",
            chat_id=1,
            message_id=2,
        )

    assert task_queue.downloads == [(request.id, 1, 2)]
    async with session_factory() as session:
        stored = await SqlAlchemyDownloadRequestRepository(session).get_by_id(request.id)
    assert stored is not None
    assert stored.spec == AudioSpec()


def test_stateless_use_cases_share_adapters(
    provider: SqlAlchemyUseCaseProvider,
) -> None:
    assert isinstance(provider.preview_download(), PreviewDownloadUseCase)
    assert isinstance(provider.trigger_ping_job(), TriggerPingJobUseCase)


# --- commit before enqueue (backlog race, fixed after ADR 0004) --------------


class _WorkerEyedQueue(_FakeTaskQueue):
    """Reads the request on enqueue from its OWN connection — what a fast
    worker picking the job up at that instant would see."""

    def __init__(self, session_factory: Any, fail: bool = False) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._fail = fail
        self.seen_at_enqueue: list[DownloadRequest | None] = []

    async def enqueue_download(self, request_id: UUID, chat_id: int, message_id: int) -> str:
        async with self._session_factory() as session:
            self.seen_at_enqueue.append(
                await SqlAlchemyDownloadRequestRepository(session).get_by_id(request_id)
            )
        if self._fail:
            raise ConnectionError("Redis is down")
        return await super().enqueue_download(request_id, chat_id, message_id)


@pytest.fixture
async def file_session_factory(tmp_path: Path) -> Any:
    # A file, not :memory: — every session must get its own connection,
    # or uncommitted rows would be visible to the "worker" and hide the race.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bot.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _provider(session_factory: Any, task_queue: Any) -> SqlAlchemyUseCaseProvider:
    return SqlAlchemyUseCaseProvider(
        session_factory=session_factory,
        task_queue=task_queue,
        downloader=object(),  # type: ignore[arg-type]  # never called here
        format_policy=FormatPolicy({}),
    )


async def _request(provider: SqlAlchemyUseCaseProvider, telegram_id: int) -> DownloadRequest:
    async with provider.request_download() as request_download:
        request: DownloadRequest = await request_download.execute(
            telegram_id,
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            AudioSpec(),
            "youtube",
            chat_id=1,
            message_id=2,
        )
    return request


@pytest.mark.asyncio
async def test_request_is_committed_before_the_job_is_enqueued(file_session_factory: Any) -> None:
    queue = _WorkerEyedQueue(file_session_factory)

    # A first-time user: the user row is created in the same call.
    request = await _request(_provider(file_session_factory, queue), 400)

    [seen] = queue.seen_at_enqueue
    assert seen is not None, "a worker taking the job now would not find the request"
    assert seen.id == request.id
    assert seen.status == DownloadStatus.PENDING


@pytest.mark.asyncio
async def test_failed_enqueue_leaves_a_failed_request_not_an_orphan(
    file_session_factory: Any,
) -> None:
    queue = _WorkerEyedQueue(file_session_factory, fail=True)

    with pytest.raises(DownloadEnqueueError):
        await _request(_provider(file_session_factory, queue), 500)

    [seen] = queue.seen_at_enqueue
    assert seen is not None
    async with file_session_factory() as session:
        stored = await SqlAlchemyDownloadRequestRepository(session).get_by_id(seen.id)
    # Not left PENDING for the reaper to "rescue" 40 minutes later.
    assert stored is not None
    assert stored.status == DownloadStatus.FAILED
