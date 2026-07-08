"""Day 9.2: language picker keyboard + explicit-locale menu rendering."""

from __future__ import annotations

import pytest

from src.presentation.telegram.i18n import create_i18n_core
from src.presentation.telegram.keyboards import (
    CB_LANG_PREFIX,
    language_picker_keyboard,
    main_menu_keyboard,
)


class FakeI18n:
    def __init__(self, core, locale: str) -> None:
        self._core = core
        self.locale = locale

    def get(self, key: str, locale: str | None = None, /, **kwargs) -> str:
        return self._core.get(key, locale or self.locale, **kwargs)


@pytest.fixture
async def core():
    c = create_i18n_core()
    await c.startup()
    return c


@pytest.mark.asyncio
async def test_picker_has_both_locales_with_bare_codes(core) -> None:
    kb = language_picker_keyboard(FakeI18n(core, "ru"))
    buttons = kb.inline_keyboard[0]
    payloads = {b.callback_data for b in buttons}
    assert payloads == {f"{CB_LANG_PREFIX}ru", f"{CB_LANG_PREFIX}en"}


@pytest.mark.asyncio
async def test_menu_renders_in_explicit_locale(core) -> None:
    # Context locale is ru, but we force en (the post-switch case).
    i18n = FakeI18n(core, "ru")
    kb_en = main_menu_keyboard(i18n, "en")
    labels = [b.text for row in kb_en.keyboard for b in row]
    assert any("Download" in text for text in labels)
    # And without override it uses the context locale (ru).
    kb_ru = main_menu_keyboard(i18n)
    labels_ru = [b.text for row in kb_ru.keyboard for b in row]
    assert any("Скачать" in text for text in labels_ru)
