"""Day 11A/11C: the user's DownloadSpec threads from the confirm button
through RequestDownloadUseCase onto the persisted request. These tests
cover the default (720p video — backward compatible) and each explicit
spec, using in-memory fakes for the repos and queue.

The matching READ chain (worker → DownloadOptions) is guarded separately
in test_process_download_spec.py — 11A.1 was precisely the case where
the write half was right and the read half was missing, so the two
halves get their own tests rather than one that could pass on either.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.application.policies.format_policy import FormatPolicy
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)


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
async def test_default_spec_is_720p_video() -> None:
    # /download passes DEFAULT_DOWNLOAD_SPEC — it must keep the exact
    # behaviour it had.
    repo = _FakeRequestRepo()
    queue = _FakeQueue()
    use_case = RequestDownloadUseCase(_FakeUserRepo(_make_user()), repo, queue, FormatPolicy({}))

    request = await use_case.execute(
        42,
        "https://youtube.com/watch?v=x",
        DEFAULT_DOWNLOAD_SPEC,
        "youtube",
        chat_id=1,
        message_id=2,
    )

    assert request.spec == VideoSpec(VideoTier.P720)
    assert repo.created is not None
    assert repo.created.spec == VideoSpec(VideoTier.P720)
    assert queue.enqueued == request.id


@pytest.mark.parametrize(
    "spec",
    [VideoSpec(VideoTier.P1080), VideoSpec(VideoTier.BEST), AudioSpec()],
)
@pytest.mark.asyncio
async def test_explicit_spec_persisted(spec: DownloadSpec) -> None:
    repo = _FakeRequestRepo()
    queue = _FakeQueue()
    use_case = RequestDownloadUseCase(_FakeUserRepo(_make_user()), repo, queue, FormatPolicy({}))

    request = await use_case.execute(
        42, "https://youtube.com/watch?v=x", spec, "youtube", chat_id=1, message_id=2
    )

    assert request.spec == spec
    assert repo.created is not None
    assert repo.created.spec == spec


def test_entity_create_defaults_to_default_spec() -> None:
    req = DownloadRequest.create(user_id=uuid4(), source_url="https://x.y")
    assert req.spec == DEFAULT_DOWNLOAD_SPEC == VideoSpec(VideoTier.P720)
