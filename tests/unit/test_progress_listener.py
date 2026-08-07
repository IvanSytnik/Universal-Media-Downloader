"""TelegramProgressListener — capture-args tests against a fake bot and a
real started Fluent core (i18n_core fixture, conftest.py), exactly the
FakeErrorLocalizer pattern used for the worker path (explicit locale,
bug #10). No real Redis — `_handle_message` is exercised directly with
hand-built pubsub-shaped message dicts, matching what redis.asyncio's
`pubsub().listen()` yields for a "pmessage".
"""

from __future__ import annotations

import json

import pytest
from aiogram.exceptions import TelegramBadRequest

from src.presentation.telegram.i18n import DEFAULT_LOCALE
from src.presentation.telegram.progress_listener import ProgressThrottler, TelegramProgressListener


class _CapturingBot:
    def __init__(self, raise_error: Exception | None = None) -> None:
        self._raise_error = raise_error
        self.edits: list[tuple[int, int, str]] = []

    async def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
        if self._raise_error is not None:
            raise self._raise_error
        self.edits.append((chat_id, message_id, text))


def _pmessage(channel: str, payload: dict) -> dict:
    return {
        "type": "pmessage",
        "pattern": "umd:progress:*",
        "channel": channel,
        "data": json.dumps(payload),
    }


@pytest.mark.asyncio
async def test_handle_message_edits_with_percent_text(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )
    message = _pmessage(
        "umd:progress:req-1",
        {
            "percent": 42.0,
            "downloaded_bytes": 420,
            "total_bytes": 1000,
            "speed": 1000.0,
            "eta": 5,
            "chat_id": 555,
            "message_id": 42,
            "language": "ru",
        },
    )

    await listener._handle_message(message)

    assert bot.edits == [(555, 42, i18n_core.get("progress-downloading", "ru", percent=42))]


@pytest.mark.asyncio
async def test_handle_message_edits_with_nostream_text(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )
    message = _pmessage(
        "umd:progress:req-2",
        {
            "percent": None,
            "downloaded_bytes": 2 * 1024 * 1024,
            "total_bytes": None,
            "speed": 1024 * 1024.0,
            "eta": None,
            "chat_id": 1,
            "message_id": 2,
            "language": "en",
        },
    )

    await listener._handle_message(message)

    assert len(bot.edits) == 1
    chat_id, message_id, text = bot.edits[0]
    assert (chat_id, message_id) == (1, 2)
    assert text == i18n_core.get("progress-downloading-nostream", "en", mb=2.0, speed="1.0 MB/s")


@pytest.mark.asyncio
async def test_handle_message_ignores_non_pmessage(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )
    await listener._handle_message({"type": "psubscribe", "channel": "umd:progress:*", "data": 1})

    assert bot.edits == []


@pytest.mark.asyncio
async def test_second_event_within_throttle_window_is_skipped(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot,
        redis=object(),  # type: ignore[arg-type]
        i18n_core=i18n_core,
        default_locale=DEFAULT_LOCALE,
        throttler=ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0),
    )
    base_payload = {
        "downloaded_bytes": 0,
        "total_bytes": 1000,
        "speed": None,
        "eta": None,
        "chat_id": 1,
        "message_id": 2,
        "language": "en",
    }

    first = _pmessage("umd:progress:req-3", {**base_payload, "percent": 10.0})
    second = _pmessage("umd:progress:req-3", {**base_payload, "percent": 12.0})
    await listener._handle_message(first)
    await listener._handle_message(second)

    # Second update: same channel, tiny step, well within the interval —
    # throttled, so only the first edit happened.
    assert len(bot.edits) == 1


@pytest.mark.asyncio
async def test_edit_message_suppresses_not_modified_error(i18n_core) -> None:
    bot = _CapturingBot(
        raise_error=TelegramBadRequest(method=None, message="Bad Request: message is not modified")  # type: ignore[arg-type]
    )
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )

    # Must not raise.
    await listener._edit_message(1, 2, "some text")


@pytest.mark.asyncio
async def test_edit_message_reraises_other_bad_requests(i18n_core) -> None:
    bot = _CapturingBot(
        raise_error=TelegramBadRequest(method=None, message="Bad Request: chat not found")  # type: ignore[arg-type]
    )
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )

    # Non-"not modified" errors are logged, not raised — progress
    # reporting must never crash the listener's long-lived loop.
    await listener._edit_message(1, 2, "some text")


@pytest.mark.asyncio
async def test_handle_message_bad_json_is_ignored(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )
    await listener._handle_message(
        {"type": "pmessage", "channel": "umd:progress:req-4", "data": "not json"}
    )

    assert bot.edits == []


@pytest.mark.asyncio
async def test_converting_phase_renders_converting_text(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )
    message = _pmessage(
        "umd:progress:req-6",
        {"phase": "converting", "chat_id": 555, "message_id": 42, "language": "ru"},
    )

    await listener._handle_message(message)

    assert bot.edits == [(555, 42, i18n_core.get("progress-converting", "ru"))]


@pytest.mark.asyncio
async def test_converting_phase_bypasses_throttle(i18n_core) -> None:
    # A "downloading" update at 99% immediately followed by "converting"
    # for the SAME channel/request must not be swallowed by the
    # interval/percent-step debounce — it's a one-shot phase transition,
    # not another point on the percent stream.
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot,
        redis=object(),  # type: ignore[arg-type]
        i18n_core=i18n_core,
        default_locale=DEFAULT_LOCALE,
        throttler=ProgressThrottler(min_interval_seconds=3.0, min_percent_step=5.0),
    )
    downloading = _pmessage(
        "umd:progress:req-7",
        {
            "percent": 99.0,
            "downloaded_bytes": 990,
            "total_bytes": 1000,
            "speed": None,
            "eta": None,
            "chat_id": 1,
            "message_id": 2,
            "language": "en",
        },
    )
    converting = _pmessage(
        "umd:progress:req-7",
        {"phase": "converting", "chat_id": 1, "message_id": 2, "language": "en"},
    )
    await listener._handle_message(downloading)
    await listener._handle_message(converting)

    assert len(bot.edits) == 2
    assert bot.edits[1] == (1, 2, i18n_core.get("progress-converting", "en"))


@pytest.mark.asyncio
async def test_handle_message_missing_coordinates_is_ignored(i18n_core) -> None:
    bot = _CapturingBot()
    listener = TelegramProgressListener(
        bot=bot, redis=object(), i18n_core=i18n_core, default_locale=DEFAULT_LOCALE  # type: ignore[arg-type]
    )
    payload = {
        "percent": 10.0,
        "downloaded_bytes": 1,
        "total_bytes": 10,
        "speed": None,
        "eta": None,
        "language": "en",
    }
    await listener._handle_message(_pmessage("umd:progress:req-5", payload))

    assert bot.edits == []
