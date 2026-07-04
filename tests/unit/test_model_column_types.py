"""Guards against the DateTime(timezone=True) mismatch bug.

Context: `completed_at`/`created_at` were declared as `Mapped[datetime]`
without an explicit `DateTime(timezone=True)`. SQLAlchemy defaulted to a
naive DateTime type for parameter binding, while the Alembic migration
had already created the columns as `TIMESTAMP WITH TIME ZONE` in
Postgres. Assigning a timezone-aware `datetime.now(UTC)` (as
DownloadRequest.mark_failed()/mark_done() do) then crashed inside
asyncpg's codec with `TypeError: can't subtract offset-naive and
offset-aware datetimes` — but only against real Postgres; the SQLite
integration tests didn't catch it because SQLite doesn't enforce this
distinction. This test checks the column definition directly instead,
so it doesn't depend on a live Postgres connection.
"""

from __future__ import annotations

from sqlalchemy import DateTime

from src.infrastructure.database.models import DownloadRequestModel, UserModel


def test_user_created_at_is_timezone_aware() -> None:
    column = UserModel.__table__.c.created_at
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True


def test_download_request_created_at_is_timezone_aware() -> None:
    column = DownloadRequestModel.__table__.c.created_at
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True


def test_download_request_completed_at_is_timezone_aware() -> None:
    column = DownloadRequestModel.__table__.c.completed_at
    assert isinstance(column.type, DateTime)
    assert column.type.timezone is True
