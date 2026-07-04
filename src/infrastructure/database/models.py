"""SQLAlchemy ORM models. Infrastructure layer only.

These are separate from domain entities (src/domain/entities/) on purpose:
ORM models know about columns, indexes, and SQL types; domain entities
know nothing about persistence. Mapping between them lives in the
repository implementations, not here and not in the domain.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.infrastructure.database.engine import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    is_premium: Mapped[bool] = mapped_column(default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    download_requests: Mapped[list[DownloadRequestModel]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_users_telegram_id", "telegram_id"),)


class DownloadRequestModel(Base):
    __tablename__ = "download_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_url: Mapped[str] = mapped_column(String(2048))
    media_type: Mapped[MediaType] = mapped_column(
        String(20), default=MediaType.UNKNOWN, server_default=MediaType.UNKNOWN.value
    )
    status: Mapped[DownloadStatus] = mapped_column(
        String(20), default=DownloadStatus.PENDING, server_default=DownloadStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[UserModel] = relationship(back_populates="download_requests")

    __table_args__ = (Index("ix_download_requests_user_id", "user_id"),)
