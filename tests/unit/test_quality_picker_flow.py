"""Day 11C stage 4: the two-step video flow, at the handler level.

Covers the four risks that only show up in a live chat:

(a) an old button's payload (no tier) must still work — pinned in
    test_confirm_callback.py;
(b) an EXPIRED token on step 2 — the user opens the picker or taps a
    tier an hour later;
(c) prefix routing — pinned in test_confirm_callback.py;
(d) a double tap on a tier must not enqueue two downloads.

Day 11C (v2): both steps are re-rendered from FormatPolicy over the
STORED context on every tap — the policy-driven cases are at the end.

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

from src.application.policies.format_policy import FormatPolicy
from src.domain.value_objects.download_spec import VideoTier
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.preview_context import PreviewContext
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

    def __init__(self, entries: dict[str, PreviewContext]) -> None:
        self._entries = dict(entries)
        self.pops: list[str] = []

    async def save(self, context: PreviewContext) -> str:  # pragma: no cover - unused
        raise NotImplementedError

    async def get(self, token: str) -> PreviewContext | None:
        return self._entries.get(token)

    async def delete(self, token: str) -> None:
        self._entries.pop(token, None)

    async def pop(self, token: str) -> PreviewContext | None:
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
_CTX = PreviewContext(
    url="https://example.com/v", extractor_key="youtube", max_compatible_short_side=1080
)
_OPEN = FormatPolicy({})


# --- step 1 -> 2 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_opening_the_picker_swaps_markup_without_consuming_the_token(
    i18n: Any,
) -> None:
    store = _Store({TOKEN: _CTX})
    message = _make_message()
    callback = _Callback(CB_QUALITY_PREFIX + TOKEN, message)

    await handle_open_quality_picker(callback, i18n, store, _OPEN)  # type: ignore[arg-type]

    assert len(message.markups) == 1
    # The token must survive: the user may still tap Back.
    assert await store.get(TOKEN) == _CTX
    assert store.pops == []


@pytest.mark.asyncio
async def test_picker_offers_every_tier_plus_back(i18n: Any) -> None:
    store = _Store({TOKEN: _CTX})
    message = _make_message()

    await handle_open_quality_picker(
        _Callback(CB_QUALITY_PREFIX + TOKEN, message),
        i18n,
        store,  # type: ignore[arg-type]
        _OPEN,
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

    await handle_open_quality_picker(callback, i18n, store, _OPEN)  # type: ignore[arg-type]

    assert message.markups == []
    assert callback.answers == [(i18n.get("flow-preview-stale"), True)]


# --- step 2 -> 1 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_back_restores_the_format_keyboard(i18n: Any) -> None:
    store = _Store({TOKEN: _CTX})
    message = _make_message()

    await handle_back_to_format(
        _Callback(CB_BACK_PREFIX + TOKEN, message),
        i18n,
        store,  # type: ignore[arg-type]
        _OPEN,
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
    store = _Store({TOKEN: _CTX})
    message = _make_message()

    for _ in range(3):
        await handle_open_quality_picker(
            _Callback(CB_QUALITY_PREFIX + TOKEN, message),
            i18n,
            store,  # type: ignore[arg-type]
            _OPEN,
        )
        await handle_back_to_format(
            _Callback(CB_BACK_PREFIX + TOKEN, message),
            i18n,
            store,  # type: ignore[arg-type]
            _OPEN,
        )

    assert len(message.markups) == 6
    assert await store.get(TOKEN) is not None


@pytest.mark.asyncio
async def test_expired_token_on_back_shows_stale_alert(i18n: Any) -> None:
    store = _Store({})
    message = _make_message()
    callback = _Callback(CB_BACK_PREFIX + TOKEN, message)

    await handle_back_to_format(callback, i18n, store, _OPEN)  # type: ignore[arg-type]

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
    store = _Store({TOKEN: _CTX})

    first = await store.pop(TOKEN)
    second = await store.pop(TOKEN)

    assert first == _CTX
    assert second is None


def test_quality_picker_keyboard_payloads_are_router_addressable() -> None:
    # Every button on step 2 must be routed by an existing prefix.
    class _Stub:
        def get(self, key: str, *a: Any, **kw: Any) -> str:
            return key

    rows = quality_picker_keyboard(
        _Stub(),  # type: ignore[arg-type]
        TOKEN,
        (VideoTier.P720, VideoTier.BEST),
        900,
    ).inline_keyboard
    payloads = [b.callback_data for row in rows for b in row]
    assert all(p.startswith(("dl:", CB_BACK_PREFIX)) for p in payloads), payloads


# --- Day 11C (v2): steps re-derived from the policy on every tap ------------


def _payloads(markup: Any) -> list[list[str]]:
    return [[b.callback_data for b in row] for row in markup.inline_keyboard]


@pytest.mark.asyncio
async def test_picker_between_tiers_offers_720_and_the_sources_best(i18n: Any) -> None:
    ctx = PreviewContext(url=_CTX.url, extractor_key="vk", max_compatible_short_side=900)
    message = _make_message()

    await handle_open_quality_picker(
        _Callback(CB_QUALITY_PREFIX + TOKEN, message),
        i18n,
        _Store({TOKEN: ctx}),  # type: ignore[arg-type]
        _OPEN,
    )

    row = message.markups[0].inline_keyboard[0]
    assert [b.callback_data for b in row] == [f"dl:{TOKEN}:v720", f"dl:{TOKEN}:vbest"]
    assert row[1].text == i18n.get("btn-quality-best", height="900")


@pytest.mark.asyncio
async def test_q_without_a_quality_step_rerenders_step_one(i18n: Any) -> None:
    # A forged q: for a TikTok-like source (h264 tops out at 720p): no
    # tiers to show, so the card falls back to step 1, whose video button
    # downloads vbest directly.
    ctx = PreviewContext(url=_CTX.url, extractor_key="tiktok", max_compatible_short_side=720)
    message = _make_message()

    await handle_open_quality_picker(
        _Callback(CB_QUALITY_PREFIX + TOKEN, message),
        i18n,
        _Store({TOKEN: ctx}),  # type: ignore[arg-type]
        _OPEN,
    )

    assert _payloads(message.markups[0]) == [
        [f"dl:{TOKEN}:vbest", f"dl:{TOKEN}:a"],
        [f"cancel:{TOKEN}"],
    ]


@pytest.mark.asyncio
async def test_kill_switch_flipped_after_render_applies_on_next_tap(i18n: Any) -> None:
    # The card was rendered with MP3; the operator disabled youtube audio
    # and restarted. Back re-renders step 1 from the policy, not from the
    # old markup, so MP3 disappears.
    message = _make_message()
    no_audio = FormatPolicy({"youtube": [FormatKind.AUDIO]})

    await handle_back_to_format(
        _Callback(CB_BACK_PREFIX + TOKEN, message),
        i18n,
        _Store({TOKEN: _CTX}),  # type: ignore[arg-type]
        no_audio,
    )

    assert _payloads(message.markups[0]) == [[CB_QUALITY_PREFIX + TOKEN], [f"cancel:{TOKEN}"]]


@pytest.mark.asyncio
async def test_q_after_video_was_disabled_shows_no_video(i18n: Any) -> None:
    message = _make_message()
    no_video = FormatPolicy({"youtube": [FormatKind.VIDEO]})

    await handle_open_quality_picker(
        _Callback(CB_QUALITY_PREFIX + TOKEN, message),
        i18n,
        _Store({TOKEN: _CTX}),  # type: ignore[arg-type]
        no_video,
    )

    assert _payloads(message.markups[0]) == [[f"dl:{TOKEN}:a"], [f"cancel:{TOKEN}"]]
