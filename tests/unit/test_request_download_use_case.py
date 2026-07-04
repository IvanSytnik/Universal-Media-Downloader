"""RequestDownloadUseCase tests using in-memory fakes — no DB, no queue."""

from __future__ import annotations

from uuid import UUID

import pytest

from src.application.use_cases.request_download import RequestDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import UnsupportedURLError


class FakeUserRepository:
    def __init__(self, existing_user: User | None = None) -> None:
        self._users: dict[UUID, User] = {}
        if existing_user is not None:
            self._users[existing_user.id] = existing_user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        for user in self._users.values():
            if user.telegram_id == telegram_id:
                return user
        return None

    async def create(self, user: User) -> User:
        self._users[user.id] = user
        return user


class FakeDownloadRequestRepository:
    def __init__(self) -> None:
        self.created: list[DownloadRequest] = []

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return next((r for r in self.created if r.id == request_id), None)

    async def create(self, download_request: DownloadRequest) -> DownloadRequest:
        self.created.append(download_request)
        return download_request

    async def update(self, download_request: DownloadRequest) -> None:
        pass

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        return [r for r in self.created if r.user_id == user_id]


class FakeTaskQueue:
    def __init__(self) -> None:
        self.enqueued_download_ids: list[UUID] = []

    async def enqueue_ping(self, message: str) -> str:
        return "fake-ping-job"

    async def enqueue_download(self, request_id: UUID) -> str:
        self.enqueued_download_ids.append(request_id)
        return "fake-download-job"


@pytest.mark.asyncio
async def test_creates_request_for_existing_user() -> None:
    existing_user = User.create_from_telegram(telegram_id=42)
    user_repo = FakeUserRepository(existing_user=existing_user)
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()

    use_case = RequestDownloadUseCase(user_repo, request_repo, task_queue)
    request = await use_case.execute(telegram_id=42, url="https://example.com/video")

    assert request.user_id == existing_user.id
    assert request.source_url == "https://example.com/video"
    assert request in request_repo.created
    assert task_queue.enqueued_download_ids == [request.id]


@pytest.mark.asyncio
async def test_registers_new_user_on_the_fly() -> None:
    user_repo = FakeUserRepository()
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()

    use_case = RequestDownloadUseCase(user_repo, request_repo, task_queue)
    request = await use_case.execute(telegram_id=999, url="https://example.com/video")

    created_user = await user_repo.get_by_telegram_id(999)
    assert created_user is not None
    assert request.user_id == created_user.id


@pytest.mark.asyncio
async def test_rejects_malformed_url_before_touching_repo_or_queue() -> None:
    user_repo = FakeUserRepository(existing_user=User.create_from_telegram(telegram_id=1))
    request_repo = FakeDownloadRequestRepository()
    task_queue = FakeTaskQueue()

    use_case = RequestDownloadUseCase(user_repo, request_repo, task_queue)

    with pytest.raises(UnsupportedURLError):
        await use_case.execute(telegram_id=1, url="not-a-url")

    assert request_repo.created == []
    assert task_queue.enqueued_download_ids == []
