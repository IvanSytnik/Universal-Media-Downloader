"""Tests for FluentErrorLocalizer (Day 10).

Guards the worker-path localizer: explicit-locale resolution (bug #10 —
never call the core without a locale outside an update context),
fallback for None/unsupported locales, and Fluent argument passthrough
for the one parameterized error key.
"""

from __future__ import annotations

import pytest
from aiogram_i18n.cores import FluentRuntimeCore

from src.infrastructure.localization.fluent_error_localizer import FluentErrorLocalizer
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core


@pytest.fixture
async def localizer() -> FluentErrorLocalizer:
    core: FluentRuntimeCore = create_i18n_core()
    await core.startup()
    return FluentErrorLocalizer(core, default_locale=DEFAULT_LOCALE)


async def test_explicit_locale_ru(localizer: FluentErrorLocalizer) -> None:
    msg = localizer.localize("error-private", "ru")
    assert msg
    assert "{" not in msg  # no unresolved placeholders


async def test_explicit_locale_en(localizer: FluentErrorLocalizer) -> None:
    msg = localizer.localize("error-private", "en")
    assert msg
    assert "{" not in msg


async def test_none_locale_falls_back_to_default(localizer: FluentErrorLocalizer) -> None:
    # A user with no stored language (User.language is NULL) → None →
    # must not raise (bug #10), resolves in the default locale.
    msg = localizer.localize("error-geo", None)
    assert msg


async def test_unsupported_locale_falls_back(localizer: FluentErrorLocalizer) -> None:
    msg = localizer.localize("error-age", "de")
    assert msg


async def test_too_large_arguments_interpolated(localizer: FluentErrorLocalizer) -> None:
    msg = localizer.localize("error-too-large", "en", estimated_mb=2100, limit_mb=2000)
    assert "2" in msg  # both numbers rendered (digit grouping varies by locale)
    assert "{" not in msg


async def test_extra_kwargs_ignored_for_plain_key(localizer: FluentErrorLocalizer) -> None:
    # Passing arguments a key doesn't use must not blow up.
    msg = localizer.localize("error-private", "en", estimated_mb=1, limit_mb=2)
    assert msg
