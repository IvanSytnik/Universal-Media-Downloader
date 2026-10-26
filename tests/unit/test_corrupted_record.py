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

* columns with a truthful fallback (media_type) degrade and log;
* ``status`` and the ``(format_kind, video_tier)`` spec pair, which have
  no non-lying fallback, raise ``CorruptedRecordError`` — a domain error
  the worker reports — never ``ValueError``.

These tests poke ``_to_entity`` with a stub row rather than going
through a database, because the point is the parsing policy, not the
SQL: Postgres will happily store any string in these varchar columns
(the only CHECK pins the kind/tier PAIRING, not the values), so a fake
row is a faithful model of what can arrive.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import structlog

from src.domain.exceptions import CorruptedRecordError
from src.domain.value_objects.download_spec import AudioSpec, VideoSpec, VideoTier
from src.domain.value_objects.enums import DownloadStatus, MediaType
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
        video_tier: str | None = "p720",
    ) -> None:
        self.id = uuid4()
        self.user_id = uuid4()
        self.source_url = "https://example.com/v"
        self.media_type = media_type
        self.status = status
        self.format_kind = format_kind
        self.video_tier = video_tier
        self.created_at = datetime.now(UTC)
        self.completed_at: datetime | None = None


def _entity(**kwargs: str | None) -> Any:
    return _to_entity(_Row(**kwargs))  # type: ignore[arg-type]


def test_clean_row_maps_straight_through() -> None:
    entity = _entity(media_type="audio", status="done", format_kind="audio", video_tier=None)
    assert entity.media_type is MediaType.AUDIO
    assert entity.status is DownloadStatus.DONE
    assert entity.spec == AudioSpec()
    assert _entity(video_tier="p1080").spec == VideoSpec(VideoTier.P1080)


def test_unknown_media_type_degrades_to_unknown() -> None:
    assert _entity(media_type="hologram").media_type is MediaType.UNKNOWN


@pytest.mark.parametrize(
    ("format_kind", "video_tier"),
    [
        ("flac", None),  # unknown kind
        ("flac", "p720"),
        ("video", "p2160"),  # unknown tier
        ("video", None),  # video without a tier
        ("audio", "p720"),  # audio with a tier
    ],
)
def test_unreadable_spec_raises_corrupted_record(format_kind: str, video_tier: str | None) -> None:
    # No honest fallback: guessing a format the user didn't pick is the
    # silent wrong delivery of 11A.1, so the pair fails loudly instead.
    row = _Row(format_kind=format_kind, video_tier=video_tier)

    with pytest.raises(CorruptedRecordError) as caught:
        _to_entity(row)  # type: ignore[arg-type]

    exc = caught.value
    assert exc.column == "spec"
    assert exc.raw_value == f"{format_kind}/{video_tier}"
    assert exc.request_id == row.id
    assert exc.error_key == "error-internal"


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
