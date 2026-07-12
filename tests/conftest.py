"""Shared test fixtures and fakes.

Day 10 note: several presentation/worker components need an
``I18nContext`` or an ``ErrorLocalizerPort`` to resolve messages. Outside
a running bot there is no aiogram update context, so these lightweight
fakes resolve keys against a REAL, started Fluent core — the tests
exercise the actual FTL files, not stubbed strings. Centralized here so
individual test modules don't each re-declare them (DRY).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core


class FakeI18n:
    """I18nContext stand-in.

    Mirrors the real ``get`` signature used across the codebase: an
    optional positional ``locale`` (some callers — e.g.
    ``main_menu_keyboard`` — pass it positionally to override the context
    locale right after a /language switch), plus Fluent kwargs. When
    ``locale`` is None it falls back to this instance's locale.
    """

    def __init__(self, core: Any, locale: str) -> None:
        self._core = core
        self.locale = locale

    def get(self, key: str, locale: str | None = None, /, **kwargs: Any) -> str:
        return self._core.get(key, locale or self.locale, **kwargs)


class FakeErrorLocalizer:
    """ErrorLocalizerPort stand-in backed by a real started core, with an
    explicit locale (mirrors FluentErrorLocalizer — bug #10)."""

    def __init__(self, core: Any, default_locale: str = DEFAULT_LOCALE) -> None:
        self._core = core
        self._default_locale = default_locale
        self._supported = set(core.locales)

    def localize(self, error_key: str, locale: str | None = None, **kwargs: Any) -> str:
        resolved = locale if locale in self._supported else self._default_locale
        return self._core.get(error_key, resolved, **kwargs)


@pytest.fixture
async def i18n_core() -> Any:
    """A started Fluent core over the real locales/ FTL files."""
    core = create_i18n_core()
    await core.startup()
    return core
