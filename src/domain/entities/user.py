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
    """

    id: UUID
    telegram_id: int | None
    is_premium: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create_from_telegram(cls, telegram_id: int) -> User:
        """Factory for the only creation path that exists as of Day 2."""
        return cls(id=uuid4(), telegram_id=telegram_id)
