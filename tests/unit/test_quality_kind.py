"""Day 11C stage 2: the QualityKind value object.

The interesting part is ``from_db_value``: a row carrying a value this
build doesn't know (written by a newer version, or hand-edited) must NOT
raise — the worker reads it after the user has already been told the
request was accepted, so a ValueError there kills an accepted job. It
degrades to HD_720 instead. Same reasoning as ProgressPhase never being
constructed from pubsub payloads (Day 11B).
"""

from __future__ import annotations

import pytest

from src.domain.value_objects.quality_kind import QualityKind


def test_enum_values_are_the_db_representation() -> None:
    assert QualityKind.HD_720.value == "hd_720"
    assert QualityKind.HD_1080.value == "hd_1080"


@pytest.mark.parametrize(
    ("quality", "expected_height"),
    [(QualityKind.HD_720, 720), (QualityKind.HD_1080, 1080)],
)
def test_max_height_is_the_single_source_of_truth(
    quality: QualityKind, expected_height: int
) -> None:
    assert quality.max_height == expected_height


@pytest.mark.parametrize("raw", ["hd_720", "hd_1080"])
def test_from_db_value_parses_known_values(raw: str) -> None:
    assert QualityKind.from_db_value(raw) is QualityKind(raw)


@pytest.mark.parametrize("raw", ["hd_2160", "", "720", "HD_720", "garbage"])
def test_from_db_value_degrades_to_default_instead_of_raising(raw: str) -> None:
    assert QualityKind.from_db_value(raw) is QualityKind.HD_720


def test_every_member_has_a_max_height() -> None:
    # Guards the match statement in ``max_height``: adding a tier without
    # a branch would make this fail loudly here instead of returning None
    # somewhere inside the downloader.
    for quality in QualityKind:
        assert isinstance(quality.max_height, int)
        assert quality.max_height > 0
