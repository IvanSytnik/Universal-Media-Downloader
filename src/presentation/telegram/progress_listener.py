"""Long-lived umd:progress:* listener — Presentation layer, Day 11B.

Runs alongside `dp.start_polling()` in main.py (Option A from
TASK_Day11B.md: same bot process, direct access to `bot` — no second
process needed). Subscribes once via PSUBSCRIBE and, for every throttled
progress event, edits the message identified by the event's own
(chat_id, message_id) — coordinates that rode in the Redis payload, no DB
lookup needed (see RedisProgressPublisher / ProgressPublisherPort).

Day 11B.1: one event kind skips the throttle entirely — a
``phase: "converting"`` payload marks the one-shot download→postprocess
boundary (audio path only, see ytdlp_downloader.py), not a point in a
percent stream, so it always renders (see _handle_message).

Explicit locale only (HANDOFF bug #10): there is no aiogram I18nContext
here — no update is in flight — so every render goes through
``i18n_core.get(key, locale, **kwargs)`` with an explicit locale, exactly
like FluentErrorLocalizer on the worker side (fluent_error_localizer.py).
Never call `.get()` bare in this module.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aiogram.exceptions import TelegramBadRequest

from src.domain.value_objects.progress_phase import ProgressPhase
from src.shared.logging import get_logger

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram_i18n.cores import FluentRuntimeCore
    from redis.asyncio import Redis

logger = get_logger(__name__)

_CHANNEL_PATTERN = "umd:progress:*"
_MIN_INTERVAL_SECONDS = 3.0
_MIN_PERCENT_STEP = 5.0
_NOT_MODIFIED_MARKER = "message is not modified"


@dataclass
class _ThrottleState:
    last_percent: float | None
    last_ts: float


class ProgressThrottler:
    """Pure debounce logic — no I/O, unit-testable in isolation.

    An update is emitted for a given ``key`` (one per in-flight download)
    only if it's the FIRST update for that key, OR both:
    - at least ``min_interval_seconds`` elapsed since the last emitted
      update for this key, AND
    - either ``percent`` is None (stream without a known total — no
      percentage to compare, so it's time-throttled only) or it moved by
      at least ``min_percent_step`` since the last emitted value.
    """

    def __init__(
        self,
        min_interval_seconds: float = _MIN_INTERVAL_SECONDS,
        min_percent_step: float = _MIN_PERCENT_STEP,
    ) -> None:
        self._min_interval_seconds = min_interval_seconds
        self._min_percent_step = min_percent_step
        self._state: dict[str, _ThrottleState] = {}

    def should_emit(self, key: str, percent: float | None, now: float) -> bool:
        state = self._state.get(key)
        if state is None:
            self._state[key] = _ThrottleState(last_percent=percent, last_ts=now)
            return True

        if now - state.last_ts < self._min_interval_seconds:
            return False

        if (
            percent is not None
            and state.last_percent is not None
            and abs(percent - state.last_percent) < self._min_percent_step
        ):
            return False

        state.last_percent = percent
        state.last_ts = now
        return True

    def discard(self, key: str) -> None:
        self._state.pop(key, None)


class TelegramProgressListener:
    def __init__(
        self,
        bot: Bot,
        redis: Redis,
        i18n_core: FluentRuntimeCore,
        default_locale: str,
        throttler: ProgressThrottler | None = None,
    ) -> None:
        self._bot = bot
        self._redis = redis
        self._i18n_core = i18n_core
        self._default_locale = default_locale
        self._throttler = throttler or ProgressThrottler()

    async def run(self) -> None:
        """Runs forever — cancel this task to stop (see main.py)."""
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(_CHANNEL_PATTERN)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                await self._handle_message(message)
        finally:
            await pubsub.punsubscribe(_CHANNEL_PATTERN)
            await pubsub.aclose()  # type: ignore[no-untyped-call]  # untyped in this redis version

    async def _handle_message(self, message: dict[str, Any]) -> None:
        channel = message["channel"]
        channel_key = channel.decode() if isinstance(channel, bytes) else str(channel)

        raw_data = message["data"]
        try:
            payload: dict[str, Any] = json.loads(raw_data)
        except (TypeError, ValueError):
            logger.warning("progress_listener_bad_payload", channel=channel_key)
            return

        # Day 11B.1: the download→postprocess boundary marker is a
        # one-shot phase transition, not a repeated percent stream — it
        # always gets through, bypassing the percent/interval debounce
        # that exists specifically to throttle a *stream* of updates.
        if payload.get("phase", ProgressPhase.DOWNLOADING) != ProgressPhase.CONVERTING:
            percent = payload.get("percent")
            if not self._throttler.should_emit(channel_key, percent, time.monotonic()):
                return

        chat_id = payload.get("chat_id")
        message_id = payload.get("message_id")
        if chat_id is None or message_id is None:
            logger.warning("progress_listener_missing_coordinates", channel=channel_key)
            return

        text = self._format_text(payload)
        await self._edit_message(chat_id, message_id, text)

    def _format_text(self, payload: dict[str, Any]) -> str:
        locale = payload.get("language") or self._default_locale
        if payload.get("phase", ProgressPhase.DOWNLOADING) == ProgressPhase.CONVERTING:
            return self._i18n_core.get("progress-converting", locale)

        percent = payload.get("percent")
        if percent is not None:
            return self._i18n_core.get("progress-downloading", locale, percent=round(percent))

        downloaded_mb = (payload.get("downloaded_bytes") or 0) / (1024 * 1024)
        speed = payload.get("speed")
        unit = "МБ/с" if locale == "ru" else "MB/s"
        speed_str = f"{speed / (1024 * 1024):.1f} {unit}" if speed else "?"
        return self._i18n_core.get(
            "progress-downloading-nostream",
            locale,
            mb=round(downloaded_mb, 1),
            speed=speed_str,
        )

    async def _edit_message(self, chat_id: int, message_id: int, text: str) -> None:
        try:
            await self._bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except TelegramBadRequest as exc:
            # Two progress events close enough to render the same text is
            # an expected race, not an error — Telegram itself is the one
            # telling us the edit is a no-op.
            if _NOT_MODIFIED_MARKER not in str(exc).lower():
                logger.warning(
                    "progress_edit_failed", chat_id=chat_id, message_id=message_id, error=str(exc)
                )
