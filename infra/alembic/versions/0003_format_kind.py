"""Day 11A: add download_requests.format_kind.

Non-nullable with a server_default of 'video', so existing rows backfill
to the pre-Day-11 behaviour (plain video download) without a separate
data-migration step, exactly as the media_type column was introduced.

Revision ID: 0003_format_kind
Revises: 0002_user_language
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_format_kind"
down_revision = "0002_user_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column(
            "format_kind",
            sa.String(length=20),
            nullable=False,
            server_default="video",
        ),
    )


def downgrade() -> None:
    op.drop_column("download_requests", "format_kind")
