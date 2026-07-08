"""Day 9 i18n tests: both locales resolve, ru pluralization, button sets."""

from __future__ import annotations

import pytest

from src.presentation.telegram.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    collect_button_translations,
    create_i18n_core,
)

# All FTL keys the Presentation layer references. If a locale is missing
# any of these, core.get raises (raise_key_error=True) — this test is the
# CI guard that keeps ru/en structurally in sync.
_REQUIRED_KEYS_SIMPLE = [
    "btn-download", "btn-help", "btn-confirm", "btn-cancel",
    "cmd-start", "cmd-download", "cmd-preview", "cmd-help",
    "start-greeting", "flow-send-url", "flow-placeholder",
    "preview-fetching", "preview-uploader-unknown", "preview-duration-unknown",
    "flow-download-started", "flow-cancelled", "flow-preview-stale",
    "error-unsupported-site", "download-usage", "download-started",
    "preview-usage", "health-ok", "worker-status-empty", "help-any-site",
]


@pytest.fixture
async def core():
    c = create_i18n_core()
    await c.startup()
    return c


@pytest.mark.asyncio
async def test_all_locales_resolve_all_simple_keys(core) -> None:
    for locale in SUPPORTED_LOCALES:
        for key in _REQUIRED_KEYS_SIMPLE:
            value = core.get(key, locale)
            assert value and value != key, f"{locale}:{key} unresolved"


@pytest.mark.asyncio
async def test_parametrized_keys_resolve(core) -> None:
    for locale in SUPPORTED_LOCALES:
        assert core.get("help-text", locale, platforms="youtube.com",
                        downloads=10, previews=5, filesize=50)
        assert core.get("preview-card", locale, title="t", uploader="u",
                        duration="1:00", mediatype="video")
        assert core.get("error-bad-url", locale, reason="x")
        assert core.get("worker-ping-enqueued", locale, jobid="abc")


@pytest.mark.asyncio
async def test_russian_pluralization(core) -> None:
    # ru has distinct one/few/many forms — the whole reason we chose Fluent.
    one = core.get("rate-limit-seconds", "ru", seconds=1)
    few = core.get("rate-limit-seconds", "ru", seconds=3)
    many = core.get("rate-limit-seconds", "ru", seconds=5)
    assert "секунду" in one
    assert "секунды" in few
    assert "секунд" in many and "секунды" not in many
    assert "минуту" in core.get("rate-limit-minutes", "ru", minutes=1)


@pytest.mark.asyncio
async def test_english_pluralization(core) -> None:
    assert "1 second" in core.get("rate-limit-seconds", "en", seconds=1)
    assert "5 seconds" in core.get("rate-limit-seconds", "en", seconds=5)


@pytest.mark.asyncio
async def test_button_translations_cover_all_locales(core) -> None:
    translations = collect_button_translations(core)
    assert "btn-download" in translations
    assert "btn-help" in translations
    # Each button's set has one entry per locale (unless two locales share
    # an identical label, which they don't here).
    assert core.get("btn-download", "ru") in translations["btn-download"]
    assert core.get("btn-download", "en") in translations["btn-download"]
    assert len(translations["btn-download"]) == len(SUPPORTED_LOCALES)


def test_default_locale_is_supported() -> None:
    assert DEFAULT_LOCALE in SUPPORTED_LOCALES


@pytest.mark.asyncio
async def test_get_without_locale_outside_request_raises(core) -> None:
    # Regression guard (Day 9): outside an update-handling context there is
    # no current I18nContext, so core.get(key) WITHOUT an explicit locale
    # tries to read the request-scoped locale and raises LookupError. Any
    # startup-time call (e.g. set_my_commands in main.py) MUST pass a locale
    # explicitly. This test locks that contract in.
    with pytest.raises(LookupError):
        core.get("cmd-start")
    # ...while passing a locale explicitly works fine.
    assert core.get("cmd-start", "en")
