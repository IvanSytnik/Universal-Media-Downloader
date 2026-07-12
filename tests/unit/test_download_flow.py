"""Unit tests for the guided download flow's pure parts: keyboards
(callback_data budget, structure) and the plain-URL routing predicate.

Day 9: keyboards are localized — labels resolve through i18n, so these
tests build a FakeI18n over the real Fluent core (same idea as
test_formatting.py's FakeI18n) and assert against the *translated*
labels. This local FakeI18n accepts an optional positional ``locale``
because ``main_menu_keyboard`` calls ``i18n.get(key, locale)`` with the
locale positionally (the /language-switch override path).
"""

from __future__ import annotations

import pytest

from src.presentation.telegram.handlers.download_flow import _looks_like_url
from src.presentation.telegram.i18n import create_i18n_core
from src.presentation.telegram.keyboards import (
    BTN_KEY_DOWNLOAD,
    BTN_KEY_HELP,
    CB_CANCEL_PREFIX,
    CB_CONFIRM_PREFIX,
    main_menu_keyboard,
    preview_confirm_keyboard,
)


class FakeI18n:
    """I18nContext stand-in that mirrors the real ``get`` signature used
    by the keyboard builders: an optional positional ``locale`` (falls
    back to this instance's locale when None), plus Fluent kwargs."""

    def __init__(self, core, locale: str) -> None:
        self._core = core
        self.locale = locale

    def get(self, key: str, locale: str | None = None, /, **kwargs) -> str:
        return self._core.get(key, locale or self.locale, **kwargs)


@pytest.fixture
async def i18n():
    core = create_i18n_core()
    await core.startup()
    return FakeI18n(core, "en")


# --- keyboards --------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_menu_is_persistent_reply_keyboard(i18n) -> None:
    # Day 8: main menu is a persistent bottom ReplyKeyboardMarkup.
    # Day 9: its labels are localized, so we assert on the translated text.
    kb = main_menu_keyboard(i18n)
    texts = [b.text for row in kb.keyboard for b in row]
    assert i18n.get(BTN_KEY_DOWNLOAD) in texts
    assert i18n.get(BTN_KEY_HELP) in texts
    assert kb.is_persistent is True
    assert kb.resize_keyboard is True


@pytest.mark.asyncio
async def test_confirm_keyboard_callback_data_fits_telegram_limit(i18n) -> None:
    token = "a" * 32  # uuid4().hex length
    kb = preview_confirm_keyboard(i18n, token)
    for row in kb.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            # Telegram hard limit: 64 bytes.
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_confirm_and_cancel_prefixes_are_distinct() -> None:
    assert CB_CONFIRM_PREFIX != CB_CANCEL_PREFIX


# --- plain-URL routing predicate --------------------------------------------


def test_looks_like_url_accepts_http_and_https() -> None:
    assert _looks_like_url("https://example.com/x") is True
    assert _looks_like_url("http://example.com/x") is True
    assert _looks_like_url("  https://example.com/x  ") is True


def test_looks_like_url_rejects_non_url() -> None:
    assert _looks_like_url("not a url") is False
    assert _looks_like_url("") is False
    assert _looks_like_url("ftp://example.com") is False