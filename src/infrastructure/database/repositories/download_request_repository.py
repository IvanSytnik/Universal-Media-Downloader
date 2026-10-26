"""SQLAlchemy implementation of DownloadRequestRepository (domain interface).

Day 11A: ``format_kind`` is mapped on read (_to_entity) and on create.
It is deliberately NOT touched in ``update``: the requested format is
fixed the moment the request is created and never changes over the
request's lifecycle (only status/completed_at do), so writing it back on
every state transition would be pointless churn.

Day 11C (v2): the request's ``DownloadSpec`` is stored as the pair
``(format_kind, video_tier)`` and follows exactly the same rule (mapped
on read and on create, never on update).

Day 11C.3 — READ-SIDE HARDENING. ``_to_entity`` used to build every enum
with its bare constructor (``MediaType(row.media_type)`` etc.). A value
this build doesn't recognize — a rolling deploy where the previous
version wrote a newer member, or a hand-edited row — made that raise
``ValueError`` from inside ``get_by_id``, i.e. after the user had
already been told their request was accepted: arq logged a traceback and
the user got nothing (bugs #6 and #13).

Now every enum column is parsed defensively, with the policy living on
the enum itself:

* ``media_type`` → UNKNOWN. The fallback is TRUE of an unreadable
  value, and it is logged here (not in the domain) because only this
  layer knows the request id — without it a warning can't lead back to
  the bad row.
* ``status`` has no honest fallback (see DownloadStatus in enums.py), so
  it raises ``CorruptedRecordError``, which the worker handles like any
  other categorized failure.
* ``(format_kind, video_tier)`` → ``DownloadSpec`` has no honest fallback
  either (Day 11C v2): delivering a format the user did not pick is the
  silent wrong delivery 11A.1 was. Any pair ``spec_from_parts`` rejects
  raises ``CorruptedRecordError(column="spec")``.

That exception is correct for ``get_by_id`` — one unreadable row means
that one request cannot be processed. It is NOT correct for
``list_by_user``: a listing is a set of independent rows, and letting one
corrupt row abort the whole query would hide every healthy request the
user has. So the listing SKIPS unreadable rows (loudly, in the log) and
returns the rest. Same data, two different right answers, because the
blast radius differs.

The single-column enums have no CHECK constraint, deliberately: the
application is the only writer, so a constraint would only restate what
the writer already guarantees. The spec pair DOES get one
(``ck_download_requests_video_tier_kind``, migration 0005): it is a
cross-column invariant the old schema could not express, and pinning it
in the schema makes the backfill provably complete. Unknown tier VALUES
still pass the CHECK, so the read path keeps its guard regardless.

Stale-request reaper (ops minimum, ADR 0004). Every write that changes a
request's status also stamps ``updated_at`` — the reaper's only liveness
signal. The two transitions a job and the reaper can race on are
compare-and-set UPDATEs (``claim_for_processing``, ``fail_stale``), each
re-checking "still active" in its WHERE, so whichever commits second
finds nothing to do instead of overwriting the first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.download_request import DownloadRequest
from src.domain.exceptions import CorruptedRecordError
from src.domain.value_objects.download_spec import (
    DownloadSpec,
    spec_from_parts,
    spec_kind,
    spec_video_tier,
)
from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.stale_request import StaleRequest
from src.infrastructure.database.models import DownloadRequestModel
from src.shared.logging import get_logger

logger = get_logger(__name__)

_ACTIVE_STATUSES = (DownloadStatus.PENDING, DownloadStatus.PROCESSING)


def _degraded(
    parsed: MediaType, raw: str, *, column: str, model: DownloadRequestModel
) -> MediaType:
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


def _parse_spec(model: DownloadRequestModel) -> DownloadSpec:
    """Strict parse of the ``(format_kind, video_tier)`` pair — see the
    module docstring for why there is no fallback."""
    try:
        return spec_from_parts(model.format_kind, model.video_tier)
    except ValueError as exc:
        raise CorruptedRecordError(
            column="spec",
            raw_value=f"{model.format_kind}/{model.video_tier}",
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
        spec=_parse_spec(model),
        created_at=model.created_at,
        completed_at=model.completed_at,
    )


def _tier_value(spec: DownloadSpec) -> str | None:
    tier = spec_video_tier(spec)
    return tier.value if tier is not None else None


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
            format_kind=spec_kind(download_request.spec).value,
            video_tier=_tier_value(download_request.spec),
            updated_at=datetime.now(UTC),
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
        model.updated_at = datetime.now(UTC)
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
        model.completed_at = model.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def claim_for_processing(self, request_id: UUID) -> bool:
        result = await self._session.execute(
            update(DownloadRequestModel)
            .where(
                DownloadRequestModel.id == request_id,
                DownloadRequestModel.status.in_(_ACTIVE_STATUSES),
            )
            .values(status=DownloadStatus.PROCESSING, updated_at=datetime.now(UTC))
            .returning(DownloadRequestModel.id)
        )
        return result.scalar_one_or_none() is not None

    async def fail_stale(self, updated_before: datetime, limit: int) -> list[StaleRequest]:
        """Two steps in the caller's transaction. The SELECT takes row
        locks and SKIPs rows another transaction holds (a job mid-claim)
        rather than waiting on them; the UPDATE re-checks the same
        condition, so a row that changed in between is left alone.
        SQLite (tests) ignores FOR UPDATE; the re-check alone keeps it
        correct there.
        """
        candidates = (
            await self._session.execute(
                select(
                    DownloadRequestModel.id,
                    DownloadRequestModel.user_id,
                    DownloadRequestModel.status,
                )
                .where(
                    DownloadRequestModel.status.in_(_ACTIVE_STATUSES),
                    DownloadRequestModel.updated_at < updated_before,
                )
                .order_by(DownloadRequestModel.updated_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not candidates:
            return []

        now = datetime.now(UTC)
        reaped = set(
            (
                await self._session.execute(
                    update(DownloadRequestModel)
                    .where(
                        DownloadRequestModel.id.in_([row.id for row in candidates]),
                        DownloadRequestModel.status.in_(_ACTIVE_STATUSES),
                        DownloadRequestModel.updated_at < updated_before,
                    )
                    .values(status=DownloadStatus.FAILED, completed_at=now, updated_at=now)
                    .returning(DownloadRequestModel.id)
                )
            ).scalars()
        )
        return [
            StaleRequest(
                request_id=row.id,
                user_id=row.user_id,
                previous_status=DownloadStatus(row.status),
            )
            for row in candidates
            if row.id in reaped
        ]

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        """Rows the user can be shown. Unreadable ones are skipped, not
        fatal — see the module docstring for why this differs from
        ``get_by_id``.

        Skipping is logged at error level with the row id: silently
        returning a short list would make a corrupt row invisible
        forever, and "my history is missing an item" is close to
        undebuggable without that line.
        """
        stmt = (
            select(DownloadRequestModel)
            .where(DownloadRequestModel.user_id == user_id)
            .order_by(DownloadRequestModel.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)

        entities: list[DownloadRequest] = []
        for model in result.scalars().all():
            try:
                entities.append(_to_entity(model))
            except CorruptedRecordError as exc:
                logger.error(
                    "download_request_skipped_in_listing",
                    request_id=str(exc.request_id),
                    user_id=str(exc.user_id),
                    column=exc.column,
                    raw_value=exc.raw_value,
                )
        return entities
