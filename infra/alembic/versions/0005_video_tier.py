"""Day 11C (v2): replace download_requests.quality_kind with video_tier.

The request's DownloadSpec is stored as ``(format_kind, video_tier)``:
``video_tier`` holds the VideoTier of a video request and is NULL exactly
for audio rows. The CHECK ``ck_download_requests_video_tier_kind`` pins
that pairing, so after this migration a row can no longer claim "mp3 at
1080p" — or "video with no tier" — at all.

``format_kind`` loses its server_default ('video', from 0003): under the
CHECK a default on only one half of the pair can never yield a valid
row, so the schema now says what is true — both columns are written by
the application. Downgrade restores it.

Upgrade backfills from the column it replaces, video rows only:
``hd_720 → p720``, ``hd_1080 → p1080``; any other value (none exist,
the application only ever wrote those two) also lands on ``p720``, the
tier those rows actually downloaded at. Audio rows stay NULL — their
``quality_kind`` was a placeholder nothing read.

Downgrade is LOSSY by design: ``quality_kind`` has no member for
``best``, so ``p1080 → hd_1080`` and everything else (``p720``, ``best``,
audio's NULL) → ``hd_720``. A BEST request downgraded and re-upgraded
comes back as P720.

Deploy order (single host, pre-launch — no expand/contract): stop bot
and worker, run ``alembic upgrade head``, start them again. Old code
reads ``quality_kind``, which this drops, so old and new code must not
run against the same schema; nothing in the arq payload changes (it is
just the request id), so the queue does not need draining.

Revision ID kept SHORT on purpose — alembic_version.version_num is
VARCHAR(32) (bug 11A.0).

Revision ID: 0005_video_tier
Revises: 0004_quality_kind
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_video_tier"
down_revision = "0004_quality_kind"
branch_labels = None
depends_on = None

_CHECK_NAME = "ck_download_requests_video_tier_kind"


def upgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column("video_tier", sa.String(length=10), nullable=True),
    )
    op.execute(
        """
        UPDATE download_requests
        SET video_tier = CASE quality_kind WHEN 'hd_1080' THEN 'p1080' ELSE 'p720' END
        WHERE format_kind = 'video'
        """
    )
    op.create_check_constraint(
        _CHECK_NAME,
        "download_requests",
        "(format_kind = 'video') = (video_tier IS NOT NULL)",
    )
    op.alter_column("download_requests", "format_kind", server_default=None)
    op.drop_column("download_requests", "quality_kind")


def downgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column(
            "quality_kind",
            sa.String(length=16),
            nullable=False,
            server_default="hd_720",
        ),
    )
    op.execute("UPDATE download_requests SET quality_kind = 'hd_1080' WHERE video_tier = 'p1080'")
    op.drop_constraint(_CHECK_NAME, "download_requests", type_="check")
    op.alter_column("download_requests", "format_kind", server_default="video")
    op.drop_column("download_requests", "video_tier")
