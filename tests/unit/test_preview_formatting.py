"""Tests for format_preview HTML-escaping.

This exists because a previous version inserted `preview.title` and
`preview.uploader` — untrusted data from YouTube/yt-dlp — directly into
a message sent with the bot's default HTML parse_mode. A title
containing '<', '>', or '&' would make Telegram reject the whole
message (TelegramBadRequest: can't parse entities). This test locks down
the general case: any external string reaching an HTML message must be
escaped. Day 9: format_preview takes an I18nContext, so tests pass a
FakeI18n over the real core.
"""

from __future__ import annotations

import pytest

from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview
from src.presentation.telegram.formatting import format_preview
from tests.conftest import FakeI18n


def _preview(title: str, uploader: str | None = "Some Channel") -> MediaPreview:
    return MediaPreview(
        source_url="https://example.com/video",
        title=title,
        duration_seconds=120,
        uploader=uploader,
        thumbnail_url=None,
        media_type=MediaType.VIDEO,
    )


@pytest.mark.asyncio
async def test_format_preview_escapes_angle_brackets_in_title(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "en")
    result = format_preview(i18n, _preview("<script>alert(1)</script>"))
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


@pytest.mark.asyncio
async def test_format_preview_escapes_ampersand_in_title(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "en")
    result = format_preview(i18n, _preview("Tom & Jerry"))
    assert "Tom & Jerry" not in result
    assert "Tom &amp; Jerry" in result


@pytest.mark.asyncio
async def test_format_preview_escapes_uploader(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "en")
    result = format_preview(i18n, _preview("Normal Title", uploader="<b>Fake Bold</b>"))
    assert "<b>Fake Bold</b>" not in result
    assert "&lt;b&gt;Fake Bold&lt;/b&gt;" in result


@pytest.mark.asyncio
async def test_format_preview_handles_missing_uploader(i18n_core) -> None:
    i18n = FakeI18n(i18n_core, "ru")
    result = format_preview(i18n, _preview("Normal Title", uploader=None))
    assert "неизвестно" in result
