"""add users.language (Day 9 — i18n locale override)

Revision ID: 0002_user_language
Revises: 0001_initial
Create Date: 2026-07-07

Adds a nullable ``language`` column to ``users``. NULL means "no explicit
override" — the Presentation layer then falls back to the Telegram
``language_code`` and finally to the configured default locale. No
backfill: existing rows keep NULL and are handled by that same fallback,
so the migration is safe to run online without a data migration step.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_user_language"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "language")
