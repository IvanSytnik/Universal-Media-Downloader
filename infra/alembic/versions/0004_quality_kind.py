"""Day 11C: add download_requests.quality_kind.

Non-nullable with a server_default of 'hd_720', so existing rows backfill
to the tier the code actually ran with before this migration (the Day 11C
stage 1 default of 720p) without a separate data-migration step — same
shape as 0003_format_kind.

String(16) rather than the tightest fit ('hd_1080' is 7 chars): the
column costs nothing extra in Postgres, and widening it later would cost
a migration.

The server_default stays in the schema permanently: it is what backfills
old rows here, and it keeps a raw INSERT that omits the column valid.

Revision ID kept SHORT on purpose — alembic_version.version_num is
VARCHAR(32), and a longer id fails the bookkeeping UPDATE *after* the DDL
has already committed (bug 11A.0).

Revision ID: 0004_quality_kind
Revises: 0003_format_kind
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_quality_kind"
down_revision = "0003_format_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column(
            "quality_kind",
            sa.String(length=16),
            nullable=False,
            server_default="hd_720",
        ),
    )


def downgrade() -> None:
    op.drop_column("download_requests", "quality_kind")
