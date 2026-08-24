"""SQLAlchemy ORM models. Infrastructure layer only."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind
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
    # Day 11A: what the user asked for (video vs mp3). server_default =
    # "video" so any row created before this migration reads back as a
    # normal video download — the pre-Day-11 behaviour, unchanged.
    format_kind: Mapped[FormatKind] = mapped_column(
        String(20), default=FormatKind.VIDEO, server_default=FormatKind.VIDEO.value
    )
    # Day 11C: requested video quality tier. NOT NULL with a
    # server_default of "hd_720" so pre-migration rows backfill to the
    # Day 11C stage 1 default (720p) — the behaviour they actually ran
    # with. Audio rows carry this value and never read it. String(16)
    # rather than the tightest fit: "hd_1080" needs 7, and a wider tier
    # name later shouldn't cost a migration.
    quality_kind: Mapped[QualityKind] = mapped_column(
        String(16), default=QualityKind.HD_720, server_default=QualityKind.HD_720.value
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[UserModel] = relationship(back_populates="download_requests")

    __table_args__ = (Index("ix_download_requests_user_id", "user_id"),)
