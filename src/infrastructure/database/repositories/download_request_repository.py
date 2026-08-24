"""SQLAlchemy implementation of DownloadRequestRepository (domain interface).

Day 11A: ``format_kind`` is mapped on read (_to_entity) and on create.
It is deliberately NOT touched in ``update``: the requested format is
fixed the moment the request is created and never changes over the
request's lifecycle (only status/completed_at do), so writing it back on
every state transition would be pointless churn.

Day 11C: ``quality_kind`` follows exactly the same rule (mapped on read
and on create, never on update).

Day 11C.3 — READ-SIDE HARDENING. ``_to_entity`` used to build every enum
with its bare constructor (``MediaType(row.media_type)`` etc.). A value
this build doesn't recognize — a rolling deploy where the previous
version wrote a newer member, or a hand-edited row — made that raise
``ValueError`` from inside ``get_by_id``, i.e. after the user had
already been told their request was accepted: arq logged a traceback and
the user got nothing (bugs #6 and #13).

Now every enum column is parsed defensively, with the policy living on
the enum itself:

* ``media_type`` → UNKNOWN, ``format_kind`` → VIDEO, ``quality_kind`` →
  HD_720. Each fallback is TRUE of an unreadable value, and each is
  logged here (not in the domain) because only this layer knows the
  request id — without it a warning can't lead back to the bad row.
* ``status`` has no honest fallback (see DownloadStatus in enums.py), so
  it raises ``CorruptedRecordError``, which the worker handles like any
  other categorized failure.

No CHECK constraint backs this up on the database side, deliberately:
the application is the only writer, so a constraint would only restate
what the writer already guarantees, while the read path needs this
guard regardless of how the bad value got there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.download_request import DownloadRequest
from src.domain.exceptions import CorruptedRecordError
from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind
from src.infrastructure.database.models import DownloadRequestModel
from src.shared.logging import get_logger

logger = get_logger(__name__)


def _degraded[E: (MediaType, FormatKind, QualityKind)](
    parsed: E, raw: str, *, column: str, model: DownloadRequestModel
) -> E:
    """Log when a stored value had to be degraded to a fallback.

    Detects the degrade by comparing against the raw string rather than
    by catching, so the enums stay pure (no logger in the domain). The
    request id is the point of the whole warning — it's what makes the
    bad row findable afterwards; the raw value says what to look for.
    """
    if parsed.value != raw:
        logger.warning(
            "download_request_column_degraded",
            request_id=str(model.id),
            column=column,
            raw_value=raw,
            fallback=parsed.value,
        )
    return parsed


def _parse_status(model: DownloadRequestModel) -> DownloadStatus:
    """Strict parse — no fallback exists that wouldn't lie.

    Reading a corrupt status as PENDING would re-run a download the user
    may already have received; as DONE it would silently swallow one
    they never got. So this raises instead — but a *domain* error the
    worker knows how to report, never a bare ValueError.
    """
    try:
        return DownloadStatus(model.status)
    except ValueError as exc:
        raise CorruptedRecordError(
            column="status",
            raw_value=str(model.status),
            request_id=model.id,
            user_id=model.user_id,
        ) from exc


def _to_entity(model: DownloadRequestModel) -> DownloadRequest:
    return DownloadRequest(
        id=model.id,
        user_id=model.user_id,
        source_url=model.source_url,
        media_type=_degraded(
            MediaType.from_db_value(model.media_type),
            model.media_type,
            column="media_type",
            model=model,
        ),
        status=_parse_status(model),
        format_kind=_degraded(
            FormatKind.from_db_value(model.format_kind),
            model.format_kind,
            column="format_kind",
            model=model,
        ),
        quality_kind=_degraded(
            QualityKind.from_db_value(model.quality_kind),
            model.quality_kind,
            column="quality_kind",
            model=model,
        ),
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
            format_kind=download_request.format_kind.value,
            quality_kind=download_request.quality_kind.value,
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

    async def mark_failed_by_id(self, request_id: UUID) -> None:
        """Mark a request failed WITHOUT loading it as an entity.

        Exists for exactly one caller: the worker's recovery path for a
        row that ``_to_entity`` could not read. ``update()`` can't serve
        it — that takes a DownloadRequest, which is the thing we failed
        to build. Writes the same two fields ``mark_failed()`` would, so
        the corrupt status is overwritten with a readable one and the
        row stops being a landmine for the next reader.
        """
        model = await self._session.get(DownloadRequestModel, request_id)
        if model is None:
            return
        model.status = DownloadStatus.FAILED
        model.completed_at = datetime.now(UTC)
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
