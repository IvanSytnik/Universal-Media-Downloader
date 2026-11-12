"""Plain text that no handler routes gets a hint instead of silence.

Routing is checked through a real aiogram Dispatcher (with a session that
records Bot API calls instead of sending them), so the filters — command,
FSM state, plain text — are exercised as aiogram applies them.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, Message, Update, User

from src.presentation.telegram.handlers.fallback import is_plain_text
from src.presentation.telegram.handlers.fallback import router as fallback_router
from src.presentation.telegram.states import DownloadFlow
from tests.conftest import FakeI18n

_CHAT_ID = 7


class _RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []

    async def make_request(
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        assert isinstance(method, SendMessage)
        self.sent.append(method.text)
        return Message(
            message_id=2,
            date=datetime.now(UTC),
            chat=Chat(id=_CHAT_ID, type="private"),
            text=method.text,
        )

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
        raise NotImplementedError
        yield b""

    async def close(self) -> None:
        return None


def _update(text: str) -> Update:
    user = User(id=_CHAT_ID, is_bot=False, first_name="t")
    return Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(UTC),
            chat=Chat(id=_CHAT_ID, type="private"),
            from_user=user,
            text=text,
        ),
    )


async def _dispatch(text: str, i18n_core: Any, state: Any = None) -> list[str]:
    session = _RecordingSession()
    bot = Bot(token="42:TEST", session=session)
    storage = MemoryStorage()
    if state is not None:
        key = StorageKey(bot_id=bot.id, chat_id=_CHAT_ID, user_id=_CHAT_ID)
        await storage.set_state(key, state)
    dp = Dispatcher(storage=storage)
    # A router has one parent, and the module-level one may already sit in
    # the dispatcher another test built: borrow it, then give it back.
    previous_parent = fallback_router._parent_router
    fallback_router._parent_router = None
    dp.include_router(fallback_router)
    try:
        await dp.feed_update(bot, _update(text), i18n=FakeI18n(i18n_core, "en"))
    finally:
        fallback_router._parent_router = previous_parent
    return session.sent


@pytest.mark.parametrize("text", ["youtube.com/watch?v=x", "hello", "ftp://example.com/f"])
async def test_plain_text_gets_the_hint(i18n_core: Any, text: str) -> None:
    assert await _dispatch(text, i18n_core) == ["Send me a link that starts with https://"]


@pytest.mark.parametrize("text", ["/unknown", "  /help extra"])
async def test_commands_are_not_taken(i18n_core: Any, text: str) -> None:
    assert await _dispatch(text, i18n_core) == []


async def test_waiting_for_url_state_is_not_taken(i18n_core: Any) -> None:
    sent = await _dispatch("youtube.com/watch?v=x", i18n_core, state=DownloadFlow.waiting_for_url)
    assert sent == []


def test_is_plain_text() -> None:
    assert is_plain_text("youtube.com/x")
    assert not is_plain_text("/start")


async def test_hint_is_localized(i18n_core: Any) -> None:
    assert i18n_core.get("hint-send-link", "ru") == "Пришли ссылку, которая начинается с https://"
