"""Day 11C stage 4: the two-step video flow, at the handler level.

Covers the four risks that only show up in a live chat:

(a) an old button's payload (no tier) must still work — pinned in
    test_confirm_callback.py;
(b) an EXPIRED token on step 2 — the user opens the picker or taps a
    tier an hour later;
(c) prefix routing — pinned in test_confirm_callback.py;
(d) a double tap on a tier must not enqueue two downloads.

The store fake mirrors the real Redis semantics that matter here: ``get``
is non-destructive, ``pop`` claims atomically. (d) is meaningless against
a fake where pop is get+delete, so the fake implements pop as a real
single-step claim.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.types import Chat, Message
from aiogram_i18n.cores import FluentRuntimeCore

from src.presentation.telegram.handlers.download_flow import (
    handle_back_to_format,
    handle_open_quality_picker,
)
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core
from src.presentation.telegram.keyboards import (
    CB_BACK_PREFIX,
    CB_QUALITY_PREFIX,
    quality_picker_keyboard,
)
from tests.conftest import FakeI18n


class _Store:
    """PreviewContextStorePort fake with REAL claim semantics."""

    def __init__(self, entries: dict[str, str]) -> None:
        self._entries = dict(entries)
        self.pops: list[str] = []

    async def save(self, url: str) -> str:  # pragma: no cover - unused
        raise NotImplementedError

    async def get(self, token: str) -> str | None:
        return self._entries.get(token)

    async def delete(self, token: str) -> None:
        self._entries.pop(token, None)

    async def pop(self, token: str) -> str | None:
        self.pops.append(token)
        return self._entries.pop(token, None)


class _Message(Message):
    """A REAL aiogram Message, with the two edit calls captured.

    Subclassing rather than duck-typing is load-bearing: the handlers
    guard every edit with ``isinstance(callback.message, Message)``
    (a MaybeInaccessibleMessage can arrive instead), so a look-alike
    silently takes the do-nothing branch and every assertion here would
    pass vacuously against handlers that do nothing at all.
    """

    @property
    def markups(self) -> list[Any]:
        return self.__dict__.setdefault("_markups", [])

    async def edit_reply_markup(self, **kwargs: Any) -> None:  # type: ignore[override]
        self.markups.append(kwargs.get("reply_markup"))


def _make_message() -> _Message:
    return _Message.model_construct(
        message_id=2,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        text="preview text",
    )


class _Callback:
    def __init__(self, data: str, message: Any) -> None:
        self.data = data
        self.message = message
        self.from_user = type("_U", (), {"id": 42})()
        self.answers: list[tuple[str | None, bool]] = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


@pytest.fixture
async def i18n() -> Any:
    core: FluentRuntimeCore = create_i18n_core()
    await core.startup()
    return FakeI18n(core, DEFAULT_LOCALE)


TOKEN = "a" * 32


# --- step 1 -> 2 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_opening_the_picker_swaps_markup_without_consuming_the_token(
    i18n: Any,
) -> None:
    store = _Store({TOKEN: "https://example.com/v"})
    message = _make_message()
    callback = _Callback(CB_QUALITY_PREFIX + TOKEN, message)

    await handle_open_quality_picker(callback, i18n, store)  # type: ignore[arg-type]

    assert len(message.markups) == 1
    # The token must survive: the user may still tap Back.
    assert await store.get(TOKEN) == "https://example.com/v"
    assert store.pops == []


@pytest.mark.asyncio
async def test_picker_offers_every_tier_plus_back(i18n: Any) -> None:
    store = _Store({TOKEN: "https://example.com/v"})
    message = _make_message()

    await handle_open_quality_picker(
        _Callback(CB_QUALITY_PREFIX + TOKEN, message),
        i18n,
        store,  # type: ignore[arg-type]
    )

    rows = message.markups[0].inline_keyboard
    tier_payloads = [b.callback_data for b in rows[0]]
    assert tier_payloads == [f"dl:{TOKEN}:v720", f"dl:{TOKEN}:v1080"]
    assert rows[1][0].callback_data == CB_BACK_PREFIX + TOKEN


@pytest.mark.asyncio
async def test_expired_token_on_opening_picker_shows_stale_alert(i18n: Any) -> None:
    # Risk (b): the preview TTL ran out while the card sat in the chat.
    # Better to say so now than to render tiers that are guaranteed to
    # fail one tap later, after the user has made a choice.
    store = _Store({})
    message = _make_message()
    callback = _Callback(CB_QUALITY_PREFIX + TOKEN, message)

    await handle_open_quality_picker(callback, i18n, store)  # type: ignore[arg-type]

    assert message.markups == []
    assert callback.answers == [(i18n.get("flow-preview-stale"), True)]


# --- step 2 -> 1 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_back_restores_the_format_keyboard(i18n: Any) -> None:
    store = _Store({TOKEN: "https://example.com/v"})
    message = _make_message()

    await handle_back_to_format(
        _Callback(CB_BACK_PREFIX + TOKEN, message),
        i18n,
        store,  # type: ignore[arg-type]
    )

    rows = message.markups[0].inline_keyboard
    # Step 1 again: the video button reopens the picker, mp3 downloads.
    assert rows[0][0].callback_data == CB_QUALITY_PREFIX + TOKEN
    assert rows[0][1].callback_data == f"dl:{TOKEN}:a"
    assert await store.get(TOKEN) is not None


@pytest.mark.asyncio
async def test_bouncing_between_steps_is_free(i18n: Any) -> None:
    # Neither leg consumes the token, so a hesitant user can toggle as
    # often as they like until the TTL expires.
    store = _Store({TOKEN: "https://example.com/v"})
    message = _make_message()

    for _ in range(3):
        await handle_open_quality_picker(
            _Callback(CB_QUALITY_PREFIX + TOKEN, message),
            i18n,
            store,  # type: ignore[arg-type]
        )
        await handle_back_to_format(
            _Callback(CB_BACK_PREFIX + TOKEN, message),
            i18n,
            store,  # type: ignore[arg-type]
        )

    assert len(message.markups) == 6
    assert await store.get(TOKEN) is not None


@pytest.mark.asyncio
async def test_expired_token_on_back_shows_stale_alert(i18n: Any) -> None:
    store = _Store({})
    message = _make_message()
    callback = _Callback(CB_BACK_PREFIX + TOKEN, message)

    await handle_back_to_format(callback, i18n, store)  # type: ignore[arg-type]

    assert message.markups == []
    assert callback.answers == [(i18n.get("flow-preview-stale"), True)]


# --- risk (d): double tap ----------------------------------------------------


@pytest.mark.asyncio
async def test_second_claim_of_a_token_returns_none() -> None:
    """The store-level guarantee the confirm handler leans on.

    ``pop`` is one atomic claim, so of two rapid taps on 720p exactly one
    gets the URL and the other gets None (and falls into the stale
    branch). The old get-then-delete let both taps read the URL before
    either delete landed, enqueueing two downloads for one click-happy
    user.
    """
    store = _Store({TOKEN: "https://example.com/v"})

    first = await store.pop(TOKEN)
    second = await store.pop(TOKEN)

    assert first == "https://example.com/v"
    assert second is None


def test_quality_picker_keyboard_payloads_are_router_addressable() -> None:
    # Every button on step 2 must be routed by an existing prefix.
    class _Stub:
        def get(self, key: str, *a: Any, **kw: Any) -> str:
            return key

    rows = quality_picker_keyboard(_Stub(), TOKEN).inline_keyboard  # type: ignore[arg-type]
    payloads = [b.callback_data for row in rows for b in row]
    assert all(p.startswith(("dl:", CB_BACK_PREFIX)) for p in payloads), payloads
