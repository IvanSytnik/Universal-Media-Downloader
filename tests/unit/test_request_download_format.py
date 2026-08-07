"""Day 11A: format_kind threads from the confirm button through
RequestDownloadUseCase onto the persisted request. These tests cover the
default (video — backward compatible) and the explicit audio path, using
in-memory fakes for the repos and queue.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.application.use_cases.request_download import RequestDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.format_kind import FormatKind


class _FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return self._user

    async def create(self, user: User) -> User:  # pragma: no cover - user exists here
        return user


class _FakeRequestRepo:
    def __init__(self) -> None:
        self.created: DownloadRequest | None = None

    async def create(self, request: DownloadRequest) -> DownloadRequest:
        self.created = request
        return request


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: UUID | None = None
        self.enqueued_coordinates: tuple[int, int] | None = None

    async def enqueue_download(self, request_id: UUID, chat_id: int, message_id: int) -> str:
        self.enqueued = request_id
        self.enqueued_coordinates = (chat_id, message_id)
        return "job-1"


def _make_user() -> User:
    return User(id=uuid4(), telegram_id=42)


@pytest.mark.asyncio
async def test_defaults_to_video() -> None:
    repo = _FakeRequestRepo()
    queue = _FakeQueue()
    use_case = RequestDownloadUseCase(_FakeUserRepo(_make_user()), repo, queue)

    request = await use_case.execute(
        42, "https://youtube.com/watch?v=x", chat_id=1, message_id=2
    )

    assert request.format_kind is FormatKind.VIDEO
    assert repo.created is not None
    assert repo.created.format_kind is FormatKind.VIDEO
    assert queue.enqueued == request.id


@pytest.mark.asyncio
async def test_explicit_audio_persisted() -> None:
    repo = _FakeRequestRepo()
    queue = _FakeQueue()
    use_case = RequestDownloadUseCase(_FakeUserRepo(_make_user()), repo, queue)

    request = await use_case.execute(
        42, "https://youtube.com/watch?v=x", FormatKind.AUDIO, chat_id=1, message_id=2
    )

    assert request.format_kind is FormatKind.AUDIO
    assert repo.created is not None
    assert repo.created.format_kind is FormatKind.AUDIO


def test_entity_and_create_default_video() -> None:
    # Entity-level default: unchanged construction still yields video.
    req = DownloadRequest.create(user_id=uuid4(), source_url="https://x.y")
    assert req.format_kind is FormatKind.VIDEO
