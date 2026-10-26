"""NotifierPort — domain interface for telling a user about the outcome
of their download. Deliberately not called "TelegramNotifier" at this
layer: the domain doesn't know Telegram exists (PROJECT_SPEC §6.1 —
Downloader must be independent from Telegram; the same principle
applies to notifications, for the same reason: a future Web/API client
will need a different notifier behind the same contract).
"""

from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.deliverable_media import DeliverableMedia


class NotifierPort(Protocol):
    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        """Delivers a completed download to the user.

        Day 11D-1: takes the media, not a bare path, so the
        implementation can deliver a playable video / audio track; it
        falls back to a plain file when the media facts are missing.

        Raises:
            NotifierError: delivery failed (file too large, user blocked
                the bot, network error, etc.) — the caller decides what
                to do next (e.g. mark the DownloadRequest failed).
        """
        ...

    async def send_text(self, telegram_id: int, text: str) -> None:
        """Delivers a plain status/error message (no file)."""
        ...
