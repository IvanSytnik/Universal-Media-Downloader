"""User domain entity.

Plain dataclass — no SQLAlchemy, no Pydantic. Domain entities must not
depend on infrastructure. The ORM model (infrastructure/database/models.py)
is a separate class; mapping between them happens in the repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(slots=True)
class User:
    """A platform user.

    `telegram_id` is nullable by design: it's one of several possible
    login methods (see PROJECT_SPEC §6.3 — API keys / JWT will be added
    for Web/Mobile/API clients in Phase 5, linked to the same `id`, not
    replacing it).

    `language` (Day 9) is the user's explicit locale override (e.g. "ru",
    "en"). ``None`` means "no explicit choice" — the Presentation layer
    then falls back to the Telegram ``language_code`` and finally to the
    configured default. Kept in the domain (not only in the ORM) because
    locale is a user attribute, not a persistence detail: Web/API clients
    (Phase 5) will set it through their own Presentation without a
    Telegram ``language_code`` to fall back on.
    """

    id: UUID
    telegram_id: int | None
    is_premium: bool = False
    language: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create_from_telegram(cls, telegram_id: int, language: str | None = None) -> User:
        """Factory for the Telegram creation path.

        ``language`` is optional: at ``/start`` we can seed it from the
        Telegram ``language_code`` so a brand-new user immediately gets a
        localized experience, without making it a mandatory argument for
        the (future) non-Telegram creation paths.
        """
        return cls(id=uuid4(), telegram_id=telegram_id, language=language)
