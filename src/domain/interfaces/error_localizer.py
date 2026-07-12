"""ErrorLocalizerPort — turns a domain error key into a localized string.

Why this exists (Day 10): the worker path (ProcessDownloadUseCase, run
inside the arq worker) has no aiogram ``I18nContext`` — there's no
Telegram update, no i18n middleware, it's a separate process. But it
still needs to send the user a localized failure message. Before Day 10
it sent a hardcoded Russian string with the raw exception text
interpolated in — two bugs at once (a non-localized literal in the
Application layer, and diagnostic leakage to the user, bug #6).

The clean fix keeps the Dependency Rule intact: the Application layer
depends on THIS domain interface, not on aiogram-i18n or Fluent. The
infrastructure provides an implementation backed by the same FTL files
the Telegram Presentation layer uses, called with an EXPLICIT locale
(mandatory outside an update context — see HANDOFF bug #10).

The ``locale`` argument is the user's stored language (``User.language``,
Day 9), or ``None`` to mean "use the default locale" — the implementation
decides the concrete default, the domain doesn't hardcode one.
"""

from __future__ import annotations

from typing import Any, Protocol


class ErrorLocalizerPort(Protocol):
    def localize(self, error_key: str, locale: str | None = None, **kwargs: Any) -> str:
        """Resolve ``error_key`` (e.g. ``"error-private"``) to a message
        in ``locale``. A ``None`` or unsupported ``locale`` falls back to
        the implementation's default locale rather than raising, so a
        failure-path message never fails to render.

        ``**kwargs`` are passed through as message arguments for keys that
        interpolate values — e.g. ``error-too-large`` takes
        ``estimated_mb`` and ``limit_mb``. Keys with no placeholders
        simply ignore any extras."""
        ...
