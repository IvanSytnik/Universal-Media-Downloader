"""TelegramNotifier tests — Bot is mocked, no real Telegram API calls."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError

from src.domain.exceptions import NotifierError
from src.infrastructure.notifier.telegram_notifier import TelegramNotifier

TEST_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


@pytest.mark.asyncio
async def test_send_file_rejects_oversized_file(tmp_path) -> None:
    big_file = tmp_path / "big.mp4"
    big_file.write_bytes(b"x" * (TEST_MAX_FILE_SIZE_BYTES + 1))

    bot = AsyncMock()
    notifier = TelegramNotifier(bot, max_file_size_bytes=TEST_MAX_FILE_SIZE_BYTES)

    with pytest.raises(NotifierError, match="слишком большой"):
        await notifier.send_file(telegram_id=1, file_path=big_file)

    bot.send_document.assert_not_called()


@pytest.mark.asyncio
async def test_send_file_calls_bot_for_normal_sized_file(tmp_path) -> None:
    small_file = tmp_path / "small.mp4"
    small_file.write_bytes(b"small content")

    bot = AsyncMock()
    notifier = TelegramNotifier(bot, max_file_size_bytes=TEST_MAX_FILE_SIZE_BYTES)

    await notifier.send_file(telegram_id=1, file_path=small_file, caption="Tom & Jerry")

    bot.send_document.assert_awaited_once()
    _, kwargs = bot.send_document.call_args
    assert kwargs["chat_id"] == 1
    # Caption must be HTML-escaped — same reasoning as preview.py's title
    # escaping (Day 4 fix): captions can contain untrusted text.
    assert kwargs["caption"] == "Tom &amp; Jerry"


@pytest.mark.asyncio
async def test_send_file_respects_injected_limit_not_a_hardcoded_one(tmp_path) -> None:
    """Day 6 regression guard: the limit must come from the constructor
    argument, not from a module-level constant — that constant was
    removed specifically because it was duplicated (and could silently
    drift) with an identical one in ProcessDownloadUseCase."""
    file_path = tmp_path / "video.mp4"
    file_path.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB

    bot = AsyncMock()
    # A tiny injected limit (1MB) must reject a 2MB file even though
    # it's far under the old hardcoded 50MB constant.
    notifier = TelegramNotifier(bot, max_file_size_bytes=1 * 1024 * 1024)

    with pytest.raises(NotifierError, match="слишком большой"):
        await notifier.send_file(telegram_id=1, file_path=file_path)


@pytest.mark.asyncio
async def test_send_file_wraps_telegram_api_error() -> None:
    small_file_bot = AsyncMock()
    small_file_bot.send_document.side_effect = TelegramAPIError(
        method="sendDocument", message="boom"
    )
    notifier = TelegramNotifier(small_file_bot, max_file_size_bytes=TEST_MAX_FILE_SIZE_BYTES)

    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
        f.write(b"content")
        f.flush()
        with pytest.raises(NotifierError):
            await notifier.send_file(telegram_id=1, file_path=Path(f.name))


@pytest.mark.asyncio
async def test_send_text_escapes_html() -> None:
    bot = AsyncMock()
    notifier = TelegramNotifier(bot, max_file_size_bytes=TEST_MAX_FILE_SIZE_BYTES)

    await notifier.send_text(telegram_id=1, text="<script>alert(1)</script>")

    bot.send_message.assert_awaited_once()
    _, kwargs = bot.send_message.call_args
    assert kwargs["text"] == "&lt;script&gt;alert(1)&lt;/script&gt;"
