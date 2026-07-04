"""Telegram implementation of NotifierPort.

Uses a standalone `aiogram.Bot` instance (not the polling Dispatcher —
the worker process has no Dispatcher, it only needs to *send* messages,
never receive them). One Bot instance is created once at worker startup
(see worker_settings.py) and reused across jobs — not recreated per
download, to avoid needless HTTP session churn.
"""

from __future__ import annotations

from html import escape as html_escape
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from src.domain.exceptions import NotifierError
from src.shared.logging import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    def __init__(self, bot: Bot, max_file_size_bytes: int) -> None:
        """`max_file_size_bytes` is injected, not hardcoded (Day 6 fix):
        it used to be a module-level constant duplicated here AND in
        ProcessDownloadUseCase — a real DRY violation, and the exact
        kind of thing that silently drifts when only one copy gets
        updated. Now both read the same value from Settings
        (`max_deliverable_file_size_bytes`), which also changes
        correctly when a local Bot API server raises the real Telegram
        limit from 50MB to 2000MB.
        """
        self._bot = bot
        self._max_file_size_bytes = max_file_size_bytes

    async def send_file(
        self, telegram_id: int, file_path: Path, caption: str | None = None
    ) -> None:
        size_bytes = file_path.stat().st_size
        if size_bytes > self._max_file_size_bytes:
            size_mb = size_bytes / (1024 * 1024)
            limit_mb = self._max_file_size_bytes // (1024 * 1024)
            raise NotifierError(
                f"Файл слишком большой для отправки в Telegram ({size_mb:.1f} МБ, "
                f"лимит {limit_mb} МБ)"
            )

        document = FSInputFile(str(file_path))
        safe_caption = html_escape(caption) if caption else None
        try:
            await self._bot.send_document(
                chat_id=telegram_id, document=document, caption=safe_caption
            )
        except TelegramAPIError as exc:
            logger.warning("notifier_send_file_failed", telegram_id=telegram_id, error=str(exc))
            raise NotifierError(str(exc)) from exc

    async def send_text(self, telegram_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=telegram_id, text=html_escape(text))
        except TelegramAPIError as exc:
            logger.warning("notifier_send_text_failed", telegram_id=telegram_id, error=str(exc))
            raise NotifierError(str(exc)) from exc
