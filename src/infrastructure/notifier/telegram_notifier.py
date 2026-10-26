"""Telegram implementation of NotifierPort.

Uses a standalone `aiogram.Bot` instance (not the polling Dispatcher —
the worker process has no Dispatcher, it only needs to *send* messages,
never receive them). One Bot instance is created once at worker startup
(see worker_settings.py) and reused across jobs — not recreated per
download, to avoid needless HTTP session churn.

Day 11D-1 — the delivery method follows the media. Until now everything
went out through ``send_document``, and whether a video played inline
was Telegram's own, unpredictable guess (the same TikTok arrived inline
once and as a file icon the next time; a 1080p YouTube merge always as a
file). Now:

* a video with width, height and duration → ``send_video`` with those
  and ``supports_streaming=True``;
* an audio track with a duration → ``send_audio`` (title, performer,
  duration — the music player);
* anything missing a fact → ``send_document``, as before. Sending a
  video with made-up dimensions would render it distorted; a document is
  still a delivery.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from src.domain.exceptions import NotifierError
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.shared.logging import describe_error, get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    def __init__(
        self,
        bot: Bot,
        max_file_size_bytes: int,
        file_upload_timeout_seconds: int,
    ) -> None:
        """`max_file_size_bytes` is the delivery ceiling, injected from
        Settings (Day 6): 50 MB on the public Bot API, up to 2000 MB with
        the local server. A larger file is refused before any upload.

        `file_upload_timeout_seconds` overrides aiogram's default 60s
        request timeout ONLY for the file-upload call. The default is
        kept for send_text — short calls should still fail fast.
        """
        self._bot = bot
        self._max_file_size_bytes = max_file_size_bytes
        self._file_upload_timeout_seconds = file_upload_timeout_seconds

    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        file_path = media.path
        size_bytes = file_path.stat().st_size
        if size_bytes > self._max_file_size_bytes:
            size_mb = size_bytes / (1024 * 1024)
            limit_mb = self._max_file_size_bytes // (1024 * 1024)
            raise NotifierError(
                f"Файл слишком большой для отправки в Telegram ({size_mb:.1f} МБ, "
                f"лимит {limit_mb} МБ)"
            )

        # The multipart filename is what the recipient sees and saves as;
        # the file on disk keeps its <id>.<ext> name.
        upload = FSInputFile(str(file_path), filename=media.filename)
        safe_caption = html_escape(caption) if caption else None
        method = "document"
        try:
            if media.is_playable_video:
                method = "video"
                await self._bot.send_video(
                    chat_id=telegram_id,
                    video=upload,
                    width=media.width,
                    height=media.height,
                    duration=media.duration_seconds,
                    supports_streaming=True,
                    caption=safe_caption,
                    request_timeout=self._file_upload_timeout_seconds,
                )
            elif media.is_playable_audio:
                method = "audio"
                await self._bot.send_audio(
                    chat_id=telegram_id,
                    audio=upload,
                    duration=media.duration_seconds,
                    # Plain text fields of the player, not parsed as HTML.
                    title=media.title,
                    performer=media.performer,
                    caption=safe_caption,
                    request_timeout=self._file_upload_timeout_seconds,
                )
            else:
                await self._bot.send_document(
                    chat_id=telegram_id,
                    document=upload,
                    caption=safe_caption,
                    request_timeout=self._file_upload_timeout_seconds,
                )
        except TelegramAPIError as exc:
            logger.warning(
                "notifier_send_file_failed",
                telegram_id=telegram_id,
                method=method,
                error=describe_error(exc),
            )
            raise NotifierError(str(exc)) from exc
        logger.info("notifier_file_sent", telegram_id=telegram_id, method=method)

    async def send_text(self, telegram_id: int, text: str) -> None:
        try:
            await self._bot.send_message(chat_id=telegram_id, text=html_escape(text))
        except TelegramAPIError as exc:
            logger.warning(
                "notifier_send_text_failed", telegram_id=telegram_id, error=describe_error(exc)
            )
            raise NotifierError(str(exc)) from exc
