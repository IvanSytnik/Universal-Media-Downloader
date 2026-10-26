"""SQLAlchemy ORM models. Infrastructure layer only."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.infrastructure.database.engine import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    is_premium: Mapped[bool] = mapped_column(default=False, server_default="false")
    # Day 9: explicit locale override. Nullable — NULL means "inherit from
    # Telegram language_code / default". String(8) comfortably fits BCP-47
    # tags we might use later ("pt-BR"), while today we only store "ru"/"en".
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
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
    # Day 11A: what the user asked for (video vs mp3). Its server_default
    # ('video', which backfilled pre-11A rows) is dropped in 0005: with the
    # CHECK below, a default on one half of the (format_kind, video_tier)
    # pair could never produce a valid row — both are app-written.
    format_kind: Mapped[FormatKind] = mapped_column(String(20))
    # Day 11C (v2): VideoTier of a VideoSpec; NULL exactly for audio rows.
    # Together with format_kind it encodes the request's DownloadSpec —
    # the CHECK below makes the pair unable to disagree (migration 0005).
    video_tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[UserModel] = relationship(back_populates="download_requests")

    __table_args__ = (
        Index("ix_download_requests_user_id", "user_id"),
        CheckConstraint(
            "(format_kind = 'video') = (video_tier IS NOT NULL)",
            name="ck_download_requests_video_tier_kind",
        ),
    )
