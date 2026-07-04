"""Tests for _format_preview HTML-escaping.

This exists because a previous version inserted `preview.title` and
`preview.uploader` — untrusted data from YouTube/yt-dlp — directly into
a message sent with the bot's default HTML parse_mode. A title
containing '<', '>', or '&' would make Telegram reject the whole
message (TelegramBadRequest: can't parse entities). The bug was first
noticed via a literal "<ссылка>" placeholder in static help text, but
the same root cause applies to any external string reaching an HTML
message — this test locks down the general case, not just the
original symptom.
"""

from __future__ import annotations

from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview
from src.presentation.telegram.handlers.preview import _format_preview


def _preview(title: str, uploader: str | None = "Some Channel") -> MediaPreview:
    return MediaPreview(
        source_url="https://example.com/video",
        title=title,
        duration_seconds=120,
        uploader=uploader,
        thumbnail_url=None,
        media_type=MediaType.VIDEO,
    )


def test_format_preview_escapes_angle_brackets_in_title() -> None:
    result = _format_preview(_preview("<script>alert(1)</script>"))
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_format_preview_escapes_ampersand_in_title() -> None:
    result = _format_preview(_preview("Tom & Jerry"))
    assert "Tom & Jerry" not in result
    assert "Tom &amp; Jerry" in result


def test_format_preview_escapes_uploader() -> None:
    result = _format_preview(_preview("Normal Title", uploader="<b>Fake Bold</b>"))
    assert "<b>Fake Bold</b>" not in result
    assert "&lt;b&gt;Fake Bold&lt;/b&gt;" in result


def test_format_preview_handles_missing_uploader() -> None:
    result = _format_preview(_preview("Normal Title", uploader=None))
    assert "неизвестно" in result
