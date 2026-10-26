"""Shared stand-ins for the download handlers' collaborators (Day 11C v2).

The use case behind ``request_download`` is the REAL
RequestDownloadUseCase over in-memory repositories, so the policy refusal
the handlers react to is the production one, not a re-implementation.
Messages are real aiogram ``Message`` subclasses: the handlers guard
every edit with ``isinstance(..., Message)``, and a look-alike would
silently take the do-nothing branch.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from aiogram.types import Chat, Message

from src.application.policies.format_policy import FormatPolicy
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.config.settings import Settings
from src.domain.entities.download_request import DownloadRequest
from src.domain.interfaces.rate_limiter import RateLimitResult
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview
from src.domain.value_objects.preview_context import PreviewContext
from tests.unit.test_request_download_use_case import (
    FakeDownloadRequestRepository,
    FakeTaskQueue,
    FakeUserRepository,
)

USER_ID = 42


def settings() -> Settings:
    return Settings(
        bot_token="test-token",  # type: ignore[arg-type]
        _env_file=None,  # type: ignore[call-arg]
    )


def preview(extractor_key: str, short_side: int | None) -> MediaPreview:
    return MediaPreview(
        source_url="https://www.youtube.com/watch?v=x",
        title="t",
        duration_seconds=None,
        thumbnail_url=None,
        uploader=None,
        media_type=MediaType.VIDEO,
        extractor_key=extractor_key,
        max_compatible_short_side=short_side,
    )


class RecordingStore:
    """PreviewContextStorePort with real claim semantics; records which
    operations a handler used."""

    def __init__(self, entries: dict[str, PreviewContext] | None = None) -> None:
        self._entries = dict(entries or {})
        self.calls: list[str] = []

    async def save(self, context: PreviewContext) -> str:
        self.calls.append("save")
        token = f"{len(self._entries):032x}"
        self._entries[token] = context
        return token

    async def get(self, token: str) -> PreviewContext | None:
        self.calls.append("get")
        return self._entries.get(token)

    async def delete(self, token: str) -> None:
        self.calls.append("delete")
        self._entries.pop(token, None)

    async def pop(self, token: str) -> PreviewContext | None:
        self.calls.append("pop")
        return self._entries.pop(token, None)


class AllowAll:
    async def acquire(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        return RateLimitResult(allowed=True)


class _PreviewUseCase:
    def __init__(self, result: MediaPreview) -> None:
        self._result = result
        self.urls: list[str] = []

    async def execute(self, url: str) -> MediaPreview:
        self.urls.append(url)
        return self._result


class Provider:
    """UseCaseProvider over the real RequestDownloadUseCase."""

    def __init__(
        self,
        policy: FormatPolicy,
        preview_result: MediaPreview | None = None,
        queue: FakeTaskQueue | None = None,
    ) -> None:
        self.requests = FakeDownloadRequestRepository()
        self.queue = queue or FakeTaskQueue()
        self._users = FakeUserRepository()
        self._policy = policy
        self.preview_use_case = _PreviewUseCase(preview_result or preview("youtube", 1080))

    @property
    def created(self) -> list[DownloadRequest]:
        return self.requests.created

    @asynccontextmanager
    async def request_download(self) -> AsyncIterator[RequestDownloadUseCase]:
        yield RequestDownloadUseCase(self._users, self.requests, self.queue, self._policy)

    def preview_download(self) -> _PreviewUseCase:
        return self.preview_use_case


class DownQueue(FakeTaskQueue):
    """The queue is unreachable (Redis down)."""

    async def enqueue_download(self, request_id: UUID, chat_id: int, message_id: int) -> str:
        raise ConnectionError("Error 111 connecting to redis:6379. Connection refused.")


class TextMessage(Message):
    """A real Message; ``answer`` returns another TextMessage (the status
    message) and both record their edits."""

    @property
    def sent(self) -> list[TextMessage]:
        return self.__dict__.setdefault("_sent", [])

    @property
    def edits(self) -> list[str]:
        return self.__dict__.setdefault("_edits", [])

    async def answer(self, text: str, **kwargs: Any) -> TextMessage:  # type: ignore[override]
        reply = make_message(text, message_id=self.message_id + 1)
        self.sent.append(reply)
        return reply

    async def edit_text(self, text: str, **kwargs: Any) -> None:  # type: ignore[override]
        self.edits.append(text)


def make_message(text: str, message_id: int = 1) -> TextMessage:
    return TextMessage.model_construct(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=Chat(id=7, type="private"),
        from_user=type("_U", (), {"id": USER_ID})(),
        text=text,
    )


class Callback:
    def __init__(self, data: str, message: Any) -> None:
        self.data = data
        self.message = message
        self.from_user = type("_U", (), {"id": USER_ID})()
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))
