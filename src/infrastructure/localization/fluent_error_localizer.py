"""Fluent-backed ErrorLocalizerPort for the worker path.

Uses the very same ``FluentRuntimeCore`` over ``locales/{locale}/`` that
the Telegram Presentation layer uses (built via
``src.presentation.telegram.i18n.create_i18n_core``), but calls it with
an EXPLICIT locale every time. This is mandatory outside an aiogram
update context: without an ``I18nContext`` in the contextvar, calling the
core without a locale raises ``LookupError`` (HANDOFF bug #10 — the exact
class of failure that broke startup in hotfix 9.1). The worker has no
such context, so every call here passes the locale positionally.

The core must be started (``await core.startup()``) before use — same as
in ``main.py``. The worker does that once at startup and hands the ready
core to this class (see worker_settings.py).
"""

from __future__ import annotations

from typing import Any

from aiogram_i18n.cores import FluentRuntimeCore


class FluentErrorLocalizer:
    """Adapter: domain ``error_key`` → localized string, explicit locale.

    Deliberately tiny and synchronous — resolving a key from an
    already-loaded Fluent core is a pure in-memory lookup, no I/O.
    """

    def __init__(self, core: FluentRuntimeCore, default_locale: str) -> None:
        self._core = core
        self._default_locale = default_locale
        self._supported = set(core.locales)

    def localize(self, error_key: str, locale: str | None = None, **kwargs: Any) -> str:
        resolved = locale if locale in self._supported else self._default_locale
        # Explicit locale — never call self._core.get(error_key) bare in a
        # non-update context (bug #10). Extra kwargs become Fluent message
        # arguments (e.g. estimated_mb/limit_mb for error-too-large).
        return self._core.get(error_key, resolved, **kwargs)
