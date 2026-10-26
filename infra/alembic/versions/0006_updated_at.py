"""Ops minimum: add download_requests.updated_at for the stale-request reaper.

``updated_at`` is the time of the request's last status transition (or
re-claim by an arq retry). The reaper fails active requests whose
``updated_at`` is older than any live job could be (see ADR 0004). It is
written explicitly by the repository on every transition — not by an ORM
``onupdate``, which would skip a re-claim that leaves the status as is.

Backfill: ``COALESCE(completed_at, created_at)`` — the last moment each
existing row is known to have changed. Active rows from before this
migration therefore look as old as they are, and the first reaper tick
after deploy fails any that are already past the threshold: that is the
point, those are exactly the requests that got stuck.

The partial index covers only active rows (pending/processing), which
are the only ones the reaper queries and a tiny fraction of the table.

Deploy order (single host): stop bot and worker, ``alembic upgrade
head``, start them. Old code would not write ``updated_at`` (the server
default would cover inserts, but not transitions). Downgrade drops the
column and the index; nothing else reads them.

Revision ID: 0006_updated_at
Revises: 0005_video_tier
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_updated_at"
down_revision = "0005_video_tier"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_download_requests_active_updated_at"


def upgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )
    op.execute("UPDATE download_requests SET updated_at = COALESCE(completed_at, created_at)")
    op.alter_column("download_requests", "updated_at", nullable=False)
    op.create_index(
        _INDEX_NAME,
        "download_requests",
        ["updated_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="download_requests")
    op.drop_column("download_requests", "updated_at")
