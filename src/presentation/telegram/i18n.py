"""i18n wiring for the Telegram Presentation layer (Day 9).

Everything locale-related is confined to this module so the rest of the
Presentation layer only ever sees message *keys*, never raw strings, and
the Application/Domain layers stay completely unaware that localization
exists (Dependency Rule — see PROJECT_SPEC §3.1).

Three responsibilities:

1. Build the Fluent core over ``locales/{locale}/`` FTL files.
2. Choose the active locale per update (the ``UserLocaleManager`` below).
3. Expose the set of translated button labels, so the guided-flow
   handlers can match a reply-keyboard tap in *any* enabled locale
   (Day 9 decision 3A — a persistent keyboard rendered in one language
   must keep working after the user switches language).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aiogram.types import User as AiogramUser
from aiogram_i18n import I18nMiddleware
from aiogram_i18n.cores import FluentRuntimeCore
from aiogram_i18n.managers import BaseManager

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Enabled locales. ``DEFAULT_LOCALE`` is the last-resort fallback when a
# user has neither an explicit override nor a recognizable Telegram
# ``language_code``. Kept here (not in Settings) because adding a locale
# is a code change anyway — new FTL files, new translated button labels.
SUPPORTED_LOCALES: tuple[str, ...] = ("ru", "en")
DEFAULT_LOCALE = "en"

# Redis key for a user's cached explicit locale override. Written by the
# future ``/language`` command (out of Day 9 scope); read here so the
# override path already works end-to-end the moment that command lands,
# without a hot-path DB read on every update. Until then the key is
# always absent, so ``get_locale`` costs one cheap Redis GET at most.
_LOCALE_CACHE_PREFIX = "umd:locale:"

# Buttons whose *text* drives routing (see keyboards.py / download_flow.py).
# The handlers can't match on a single constant anymore — the same button
# reads "⬇️ Скачать" or "⬇️ Download" depending on locale — so they match
# against the set of all translations of these keys instead.
_BUTTON_KEYS: tuple[str, ...] = ("btn-download", "btn-help")


def locales_dir() -> Path:
    """Absolute path to the ``locales/`` directory at the project root.

    Resolved from this file's location (…/src/presentation/telegram/i18n.py
    → three parents up to the project root) rather than a CWD-relative
    path, so it works identically under pytest, ``python -m src.main`` and
    inside the Docker image (where the code lives at ``/app``).
    """
    return Path(__file__).resolve().parents[3] / "locales"


def create_i18n_core() -> FluentRuntimeCore:
    """Fluent core over ``locales/{locale}/*.ftl``.

    ``raise_key_error=True`` (the library default, made explicit) turns a
    missing translation key into a hard error instead of silently echoing
    the key back — we want that failure to surface in tests/CI, not in a
    user's chat.
    """
    return FluentRuntimeCore(
        path=str(locales_dir() / "{locale}"),
        default_locale=DEFAULT_LOCALE,
        raise_key_error=True,
    )


class UserLocaleManager(BaseManager):
    """Locale selection: explicit override → Telegram language → default.

    The override is read from Redis (populated by a future ``/language``
    command), NOT from Postgres on every update: locale is needed on the
    hot path of *every* message, and a per-update DB round-trip for a
    value that is ``NULL`` for essentially all users today would be pure
    waste (Day 9 decision 2A). ``User.language`` in Postgres remains the
    durable source of truth; the Redis entry is a write-through cache the
    ``/language`` command will maintain.
    """

    def __init__(self, redis: Redis | None = None, default_locale: str = DEFAULT_LOCALE) -> None:
        super().__init__(default_locale=default_locale)
        self._redis = redis

    def _normalize(self, raw: str | None) -> str | None:
        """Map an arbitrary language tag to one of our supported locales.

        Telegram sends full BCP-47-ish tags ("en-US", "ru", "de"). We only
        ship ru/en, so we match on the primary subtag and drop anything we
        don't translate (it'll fall through to the default).
        """
        if not raw:
            return None
        primary = raw.split("-", 1)[0].lower()
        return primary if primary in SUPPORTED_LOCALES else None

    async def get_locale(self, event_from_user: AiogramUser | None = None) -> str:
        # 1. Explicit override (Redis cache, maintained by /language later).
        if self._redis is not None and event_from_user is not None:
            cached = await self._redis.get(f"{_LOCALE_CACHE_PREFIX}{event_from_user.id}")
            if cached is not None:
                decoded = cached.decode() if isinstance(cached, bytes) else str(cached)
                normalized = self._normalize(decoded)
                if normalized is not None:
                    return normalized
        # 2. Telegram-reported UI language.
        if event_from_user is not None:
            from_telegram = self._normalize(event_from_user.language_code)
            if from_telegram is not None:
                return from_telegram
        # 3. Configured default.
        return self.default_locale or DEFAULT_LOCALE

    async def set_locale(self, locale: str, event_from_user: AiogramUser | None = None) -> None:
        """Write-through the override to Redis (used by the future
        ``/language`` command; Postgres persistence is handled separately
        by ``UserRepository.set_language`` so the choice survives a cache
        eviction)."""
        if self._redis is None or event_from_user is None:
            return
        await self._redis.set(f"{_LOCALE_CACHE_PREFIX}{event_from_user.id}", locale)


def create_i18n_middleware(
    core: FluentRuntimeCore, redis: Redis | None = None
) -> I18nMiddleware:
    return I18nMiddleware(
        core=core,
        manager=UserLocaleManager(redis=redis, default_locale=DEFAULT_LOCALE),
        default_locale=DEFAULT_LOCALE,
    )


def collect_button_translations(core: FluentRuntimeCore) -> dict[str, frozenset[str]]:
    """For each routing button key, the set of its texts across all locales.

    This is what lets a reply-keyboard tap be recognized regardless of the
    locale the keyboard was rendered in (decision 3A). Built once at
    startup from the same FTL the keyboards use — no separate list of
    button labels to keep in sync (DRY).
    """
    result: dict[str, frozenset[str]] = {}
    for key in _BUTTON_KEYS:
        texts = {core.get(key, locale) for locale in SUPPORTED_LOCALES}
        result[key] = frozenset(texts)
    return result
