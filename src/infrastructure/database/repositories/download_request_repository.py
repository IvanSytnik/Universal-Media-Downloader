"""SQLAlchemy implementation of DownloadRequestRepository (domain interface).

Not wired into any use case yet (that's Day 5) — exists now because the
table exists now. Covered by tests so it doesn't sit as untested dead code.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.download_request import DownloadRequest
from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.infrastructure.database.models import DownloadRequestModel


def _to_entity(model: DownloadRequestModel) -> DownloadRequest:
    return DownloadRequest(
        id=model.id,
        user_id=model.user_id,
        source_url=model.source_url,
        media_type=MediaType(model.media_type),
        status=DownloadStatus(model.status),
        created_at=model.created_at,
        completed_at=model.completed_at,
    )


class SqlAlchemyDownloadRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        model = await self._session.get(DownloadRequestModel, request_id)
        return _to_entity(model) if model else None

    async def create(self, download_request: DownloadRequest) -> DownloadRequest:
        model = DownloadRequestModel(
            id=download_request.id,
            user_id=download_request.user_id,
            source_url=download_request.source_url,
            media_type=download_request.media_type.value,
            status=download_request.status.value,
        )
        self._session.add(model)
        await self._session.flush()
        return download_request

    async def update(self, download_request: DownloadRequest) -> None:
        model = await self._session.get(DownloadRequestModel, download_request.id)
        if model is None:
            raise ValueError(f"DownloadRequest {download_request.id} not found")
        model.status = download_request.status
        model.completed_at = download_request.completed_at
        await self._session.flush()

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        stmt = (
            select(DownloadRequestModel)
            .where(DownloadRequestModel.user_id == user_id)
            .order_by(DownloadRequestModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [_to_entity(model) for model in result.scalars().all()]
