"""Day 11C.3: the read path never lets a bad stored value escape as a
bare ValueError.

Before this, ``_to_entity`` built every enum with its bare constructor.
An unrecognized value — a rolling deploy where the newer version wrote a
member this build doesn't have, or a hand-edited row — raised
``ValueError`` from inside ``get_by_id``, *after* the user had been told
their request was accepted: arq logged a traceback, the user got
nothing. That's bugs #6/#13 (every failure reaches the user
classified and clean).

Two policies, tested separately here:

* columns with a truthful fallback (media_type/format_kind/quality_kind)
  degrade and log;
* ``status``, which has no non-lying fallback, raises
  ``CorruptedRecordError`` — a domain error the worker reports — never
  ``ValueError``.

These tests poke ``_to_entity`` with a stub row rather than going
through a database, because the point is the parsing policy, not the
SQL: Postgres will happily store any string in these varchar columns
(there is deliberately no CHECK constraint), so a fake row is a faithful
model of what can arrive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import structlog

from src.domain.exceptions import CorruptedRecordError
from src.domain.value_objects.enums import DownloadStatus, MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind
from src.infrastructure.database.repositories.download_request_repository import _to_entity


class _Row:
    """Stand-in for DownloadRequestModel with raw strings in the enum
    columns — exactly what the DB hands back."""

    def __init__(
        self,
        *,
        media_type: str = "video",
        status: str = "pending",
        format_kind: str = "video",
        quality_kind: str = "hd_720",
    ) -> None:
        self.id = uuid4()
        self.user_id = uuid4()
        self.source_url = "https://example.com/v"
        self.media_type = media_type
        self.status = status
        self.format_kind = format_kind
        self.quality_kind = quality_kind
        self.created_at = datetime.now(UTC)
        self.completed_at: datetime | None = None


def _entity(**kwargs: str) -> Any:
    return _to_entity(_Row(**kwargs))  # type: ignore[arg-type]


def test_clean_row_maps_straight_through() -> None:
    entity = _entity(
        media_type="audio", status="done", format_kind="audio", quality_kind="hd_1080"
    )
    assert entity.media_type is MediaType.AUDIO
    assert entity.status is DownloadStatus.DONE
    assert entity.format_kind is FormatKind.AUDIO
    assert entity.quality_kind is QualityKind.HD_1080


def test_unknown_media_type_degrades_to_unknown() -> None:
    assert _entity(media_type="hologram").media_type is MediaType.UNKNOWN


def test_unknown_format_kind_degrades_to_video() -> None:
    assert _entity(format_kind="flac").format_kind is FormatKind.VIDEO


def test_unknown_quality_kind_degrades_to_default_tier() -> None:
    assert _entity(quality_kind="hd_2160").quality_kind is QualityKind.HD_720


def test_unknown_status_raises_corrupted_record_not_value_error() -> None:
    row = _Row(status="garbage")

    with pytest.raises(CorruptedRecordError) as caught:
        _to_entity(row)  # type: ignore[arg-type]

    exc = caught.value
    assert exc.column == "status"
    assert exc.raw_value == "garbage"
    # The two ids are what makes recovery possible at all: the worker
    # can't build the entity, so it has nothing else to fail/notify with.
    assert exc.request_id == row.id
    assert exc.user_id == row.user_id
    assert exc.error_key == "error-internal"


def test_corrupted_record_error_is_not_a_value_error() -> None:
    # Guards the actual regression: a bare ValueError escaping get_by_id
    # is what killed the job unhandled.
    assert not issubclass(CorruptedRecordError, ValueError)


def test_degraded_column_is_logged_with_the_request_id() -> None:
    # The id is the whole point of the warning — without it a bad row
    # can't be found afterwards. Captured through structlog rather than
    # caplog: structlog isn't wired to stdlib logging in tests, so caplog
    # silently sees nothing and any assertion on it passes vacuously.
    row = _Row(media_type="hologram")

    with structlog.testing.capture_logs() as logs:
        _to_entity(row)  # type: ignore[arg-type]

    assert len(logs) == 1
    entry = logs[0]
    assert entry["log_level"] == "warning"
    assert entry["request_id"] == str(row.id)
    assert entry["column"] == "media_type"
    assert entry["raw_value"] == "hologram"
    assert entry["fallback"] == "unknown"


def test_clean_row_logs_nothing() -> None:
    with structlog.testing.capture_logs() as logs:
        _to_entity(_Row())  # type: ignore[arg-type]

    assert logs == []


def test_each_degraded_column_is_named_in_its_own_warning() -> None:
    # All three at once: one warning per column, each naming itself, so a
    # multi-column mess is diagnosable from the log alone.
    row = _Row(media_type="hologram", format_kind="flac", quality_kind="hd_2160")

    with structlog.testing.capture_logs() as logs:
        _to_entity(row)  # type: ignore[arg-type]

    assert {entry["column"] for entry in logs} == {"media_type", "format_kind", "quality_kind"}
