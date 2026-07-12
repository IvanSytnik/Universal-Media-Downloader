"""formatting.py under i18n: data-driven help, HTML escaping, localization."""

from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview
from src.presentation.telegram.formatting import (
    format_duration,
    format_help,
    format_preview,
    format_retry_after,
)
from src.presentation.telegram.i18n import create_i18n_core


class FakeI18n:
    """Minimal I18nContext stand-in: resolves a key in a fixed locale
    through a real started core, so tests exercise the actual FTL."""

    def __init__(self, core, locale: str) -> None:
        self._core = core
        self.locale = locale

    def get(self, key: str, /, **kwargs) -> str:
        return self._core.get(key, self.locale, **kwargs)


@pytest.fixture
async def core():
    c = create_i18n_core()
    await c.startup()
    return c


def _settings() -> Settings:
    return Settings(
        allowed_domains=["youtube.com", "tiktok.com"],
        rate_limit_downloads_per_hour=10,
        rate_limit_previews_per_minute=5,
        max_deliverable_file_size_mb=50,
    )


def _preview(
    *,
    title: str,
    uploader: str | None,
    duration_seconds: int | None,
    media_type: MediaType = MediaType.VIDEO,
) -> MediaPreview:
    return MediaPreview(
        source_url="https://example.com/video",
        title=title,
        duration_seconds=duration_seconds,
        uploader=uploader,
        thumbnail_url=None,
        media_type=media_type,
    )


@pytest.mark.asyncio
async def test_help_is_data_driven(core) -> None:
    i18n = FakeI18n(core, "ru")
    text = format_help(i18n, _settings())
    # Platforms from the allowlist, limits from Settings — DRY preserved.
    assert "youtube.com" in text
    assert "tiktok.com" in text
    assert "10" in text
    assert "50" in text


@pytest.mark.asyncio
async def test_help_localized(core) -> None:
    ru = format_help(FakeI18n(core, "ru"), _settings())
    en = format_help(FakeI18n(core, "en"), _settings())
    assert ru != en
    assert "платформы" in ru.lower()
    assert "platforms" in en.lower()


@pytest.mark.asyncio
async def test_preview_escapes_html(core) -> None:
    i18n = FakeI18n(core, "en")
    preview = _preview(
        title="<script>alert(1)</script>",
        uploader="a & b",
        duration_seconds=90,
    )
    text = format_preview(i18n, preview)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "a &amp; b" in text
    assert "1:30" in text


@pytest.mark.asyncio
async def test_preview_unknown_uploader_localized(core) -> None:
    preview = _preview(title="t", uploader=None, duration_seconds=None)
    ru = format_preview(FakeI18n(core, "ru"), preview)
    en = format_preview(FakeI18n(core, "en"), preview)
    assert "неизвестно" in ru
    assert "unknown" in en


def test_format_duration_no_i18n_needed_for_numeric() -> None:
    # duration is numeric formatting; only the "unknown" branch needs i18n.
    class _Dummy:
        locale = "en"

        def get(self, key, /, **kw):  # noqa: ANN001
            return "unknown"

    assert format_duration(_Dummy(), 3661) == "1:01:01"
    assert format_duration(_Dummy(), 59) == "0:59"
    assert format_duration(_Dummy(), None) == "unknown"


@pytest.mark.asyncio
async def test_retry_after_switches_unit_and_localizes(core) -> None:
    ru = FakeI18n(core, "ru")
    assert "сек" in format_retry_after(ru, 30)
    assert "мин" in format_retry_after(ru, 120)
    # ceil: 61s → 2 min, never under-promising.
    assert "2" in format_retry_after(ru, 61)
