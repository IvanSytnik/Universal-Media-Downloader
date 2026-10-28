"""TelegramNotifier tests — Bot is mocked, no real Telegram API calls.

Day 11D-1: the delivery method follows the media — a video with its
facts is a ``send_video``, an audio track with a duration a
``send_audio``, anything missing a fact a ``send_document``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramAPIError
from aiogram.methods import SendAudio, SendDocument, SendVideo
from aiogram.methods.base import TelegramMethod
from aiogram.types import Message

from src.domain.exceptions import NotifierError
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.format_kind import FormatKind
from src.infrastructure.notifier.telegram_notifier import TelegramNotifier

TEST_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
# Day 8.1: TelegramNotifier requires an explicit upload timeout (the
# default aiogram 60s request timeout aborts large uploads). Any value
# works for these tests since the Bot is mocked and nothing is uploaded.
TEST_UPLOAD_TIMEOUT_SECONDS = 1800


def _notifier(bot: AsyncMock, max_bytes: int = TEST_MAX_FILE_SIZE_BYTES) -> TelegramNotifier:
    return TelegramNotifier(
        bot,
        max_file_size_bytes=max_bytes,
        file_upload_timeout_seconds=TEST_UPLOAD_TIMEOUT_SECONDS,
    )


def _file(tmp_path: Path, size: int = 13, name: str = "v.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return path


def _video(path: Path, **overrides: object) -> DeliverableMedia:
    facts: dict[str, object] = {
        "width": 1080,
        "height": 1920,
        "duration_seconds": 38,
        "title": "t",
        "performer": "p",
    }
    facts.update(overrides)
    return DeliverableMedia(path=path, kind=FormatKind.VIDEO, **facts)  # type: ignore[arg-type]


def _audio(path: Path, **overrides: object) -> DeliverableMedia:
    facts: dict[str, object] = {
        "duration_seconds": 2808,
        "title": "Talk <live>",
        "performer": "Chan & Co",
    }
    facts.update(overrides)
    return DeliverableMedia(path=path, kind=FormatKind.AUDIO, **facts)  # type: ignore[arg-type]


# --- method selection ------------------------------------------------------------


async def test_video_with_facts_is_sent_as_a_streamable_video(tmp_path: Path) -> None:
    bot = AsyncMock()
    await _notifier(bot).send_file(1, _video(_file(tmp_path)))

    bot.send_video.assert_awaited_once()
    bot.send_document.assert_not_called()
    kwargs = bot.send_video.call_args.kwargs
    assert (kwargs["width"], kwargs["height"], kwargs["duration"]) == (1080, 1920, 38)
    assert kwargs["supports_streaming"] is True
    assert kwargs["request_timeout"] == TEST_UPLOAD_TIMEOUT_SECONDS


async def test_audio_with_duration_is_sent_to_the_player(tmp_path: Path) -> None:
    bot = AsyncMock()
    await _notifier(bot).send_file(1, _audio(_file(tmp_path, name="a.mp3")))

    bot.send_audio.assert_awaited_once()
    kwargs = bot.send_audio.call_args.kwargs
    assert kwargs["duration"] == 2808
    # Player fields are plain text, not parse_mode HTML: no escaping.
    assert (kwargs["title"], kwargs["performer"]) == ("Talk <live>", "Chan & Co")
    assert kwargs["request_timeout"] == TEST_UPLOAD_TIMEOUT_SECONDS


@pytest.mark.parametrize("missing", ["width", "height", "duration_seconds"])
async def test_video_missing_a_fact_falls_back_to_a_document(tmp_path: Path, missing: str) -> None:
    # Made-up dimensions would render the video distorted.
    bot = AsyncMock()
    await _notifier(bot).send_file(1, _video(_file(tmp_path), **{missing: None}))

    bot.send_video.assert_not_called()
    bot.send_document.assert_awaited_once()


async def test_audio_without_duration_falls_back_to_a_document(tmp_path: Path) -> None:
    bot = AsyncMock()
    await _notifier(bot).send_file(1, _audio(_file(tmp_path), duration_seconds=None))

    bot.send_audio.assert_not_called()
    bot.send_document.assert_awaited_once()


async def test_caption_is_html_escaped_on_every_method(tmp_path: Path) -> None:
    # Same reasoning as preview.py's title escaping (Day 4): captions can
    # contain untrusted text.
    path = _file(tmp_path)
    for media, method in (
        (_video(path), "send_video"),
        (_audio(path), "send_audio"),
        (_video(path, width=None), "send_document"),
    ):
        bot = AsyncMock()
        await _notifier(bot).send_file(1, media, caption="Tom & Jerry")
        assert getattr(bot, method).call_args.kwargs["caption"] == "Tom &amp; Jerry"


@pytest.mark.parametrize(
    ("method", "field"),
    [("send_video", "video"), ("send_audio", "audio"), ("send_document", "document")],
)
async def test_upload_is_named_by_the_title_on_every_method(
    tmp_path: Path, method: str, field: str
) -> None:
    path = _file(tmp_path, name="dQw4w9WgXcQ.mp4")
    media = {
        "send_video": _video(path, title="Кино: Группа крови"),
        "send_audio": _audio(path, title="Кино: Группа крови"),
        "send_document": _video(path, width=None, title="Кино: Группа крови"),
    }[method]
    bot = AsyncMock()

    await _notifier(bot).send_file(1, media)

    upload = getattr(bot, method).call_args.kwargs[field]
    assert upload.filename == "Кино Группа крови.mp4"
    # The file read from disk is still the id-named one.
    assert Path(upload.path) == path


async def test_upload_without_title_keeps_the_id_name(tmp_path: Path) -> None:
    path = _file(tmp_path, name="dQw4w9WgXcQ.mp4")
    bot = AsyncMock()

    await _notifier(bot).send_file(1, _video(path, title=None))

    assert bot.send_video.call_args.kwargs["video"].filename == "dQw4w9WgXcQ.mp4"


# --- size ceiling and errors -------------------------------------------------------


async def test_send_file_rejects_oversized_file(tmp_path: Path) -> None:
    bot = AsyncMock()

    with pytest.raises(NotifierError, match="too large"):
        await _notifier(bot).send_file(1, _video(_file(tmp_path, TEST_MAX_FILE_SIZE_BYTES + 1)))

    bot.send_video.assert_not_called()
    bot.send_document.assert_not_called()


async def test_send_file_respects_injected_limit_not_a_hardcoded_one(tmp_path: Path) -> None:
    """Day 6 regression guard: the limit must come from the constructor
    argument, not from a module-level constant — that constant was
    removed specifically because it was duplicated (and could silently
    drift) with an identical one in ProcessDownloadUseCase."""
    bot = AsyncMock()
    # A tiny injected limit (1MB) must reject a 2MB file even though
    # it's far under the old hardcoded 50MB constant.
    notifier = _notifier(bot, max_bytes=1 * 1024 * 1024)

    with pytest.raises(NotifierError, match="too large"):
        await notifier.send_file(1, _video(_file(tmp_path, 2 * 1024 * 1024)))


@pytest.mark.parametrize("method", ["send_video", "send_audio", "send_document"])
async def test_telegram_api_error_is_wrapped_for_every_method(tmp_path: Path, method: str) -> None:
    bot = AsyncMock()
    api_method: TelegramMethod[Message] = {
        "send_video": SendVideo(chat_id=1, video="v"),
        "send_audio": SendAudio(chat_id=1, audio="a"),
        "send_document": SendDocument(chat_id=1, document="d"),
    }[method]
    getattr(bot, method).side_effect = TelegramAPIError(method=api_method, message="boom")
    path = _file(tmp_path)
    media = {
        "send_video": _video(path),
        "send_audio": _audio(path),
        "send_document": _video(path, height=None),
    }[method]

    with pytest.raises(NotifierError):
        await _notifier(bot).send_file(1, media)


async def test_send_text_escapes_html() -> None:
    bot = AsyncMock()
    notifier = _notifier(bot)

    await notifier.send_text(telegram_id=1, text="<script>alert(1)</script>")

    bot.send_message.assert_awaited_once()
    _, kwargs = bot.send_message.call_args
    assert kwargs["text"] == "&lt;script&gt;alert(1)&lt;/script&gt;"
