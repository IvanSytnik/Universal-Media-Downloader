"""Day 11A: the preview confirm button now carries the chosen format in
its callback_data. These tests pin the encode/decode contract, including
the two things most likely to bite in production:

1. Backward compatibility with the legacy bare ``dl:<token>`` payload
   (a button rendered before this deploy, still in someone's chat).
2. The 64-byte callback_data budget — a uuid4 token + prefix + suffix
   must fit with room to spare.
"""

from __future__ import annotations

import uuid

from src.domain.value_objects.format_kind import FormatKind
from src.presentation.telegram.keyboards import (
    CB_CONFIRM_PREFIX,
    confirm_callback_data,
    parse_confirm_callback,
)


def test_roundtrip_video() -> None:
    token = uuid.uuid4().hex
    data = confirm_callback_data(token, FormatKind.VIDEO)
    assert parse_confirm_callback(data) == (token, FormatKind.VIDEO)


def test_roundtrip_audio() -> None:
    token = uuid.uuid4().hex
    data = confirm_callback_data(token, FormatKind.AUDIO)
    assert parse_confirm_callback(data) == (token, FormatKind.AUDIO)


def test_legacy_bare_token_defaults_to_video() -> None:
    # Pre-Day-11 buttons had no format suffix; they must still resolve,
    # defaulting to the old behaviour (video).
    token = uuid.uuid4().hex
    assert parse_confirm_callback(CB_CONFIRM_PREFIX + token) == (token, FormatKind.VIDEO)


def test_unknown_format_code_falls_back_to_video() -> None:
    # A malformed/forged suffix should degrade to the safe default, not
    # raise inside the handler.
    token = uuid.uuid4().hex
    assert parse_confirm_callback(f"{CB_CONFIRM_PREFIX}{token}:z") == (token, FormatKind.VIDEO)


def test_callback_data_within_telegram_budget() -> None:
    token = uuid.uuid4().hex
    for fk in (FormatKind.VIDEO, FormatKind.AUDIO):
        data = confirm_callback_data(token, fk)
        assert len(data.encode("utf-8")) <= 64


def test_confirm_prefix_preserved_for_router_match() -> None:
    # The existing router uses F.data.startswith(CB_CONFIRM_PREFIX); both
    # format buttons must still start with it.
    token = uuid.uuid4().hex
    for fk in (FormatKind.VIDEO, FormatKind.AUDIO):
        assert confirm_callback_data(token, fk).startswith(CB_CONFIRM_PREFIX)
