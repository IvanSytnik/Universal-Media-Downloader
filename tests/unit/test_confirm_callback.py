"""Day 11A: the preview confirm button carries the chosen format in its
callback_data. Day 11C stage 4: for video it carries the quality tier
too, and two new payloads join it (``q:``/``back:``).

These tests pin the encode/decode contract, including the things most
likely to bite in production:

1. Every HISTORICAL payload form still resolves. Inline buttons live in
   users' chats indefinitely — a callback arriving today may have been
   rendered by any past deploy, and there is no version negotiation.
2. The 64-byte callback_data budget.
3. Prefix hygiene between routers: no callback prefix may be a prefix of
   another, or a ``startswith`` filter silently steals another handler's
   payloads depending on router registration order.
"""

from __future__ import annotations

import uuid

from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind
from src.presentation.telegram.keyboards import (
    CB_BACK_PREFIX,
    CB_CANCEL_PREFIX,
    CB_CONFIRM_PREFIX,
    CB_FLOW_DOWNLOAD,
    CB_FLOW_HELP,
    CB_LANG_PREFIX,
    CB_QUALITY_PREFIX,
    confirm_callback_data,
    parse_confirm_callback,
)


def test_roundtrip_video_defaults_to_720() -> None:
    token = uuid.uuid4().hex
    data = confirm_callback_data(token, FormatKind.VIDEO)
    assert parse_confirm_callback(data) == (token, FormatKind.VIDEO, QualityKind.HD_720)


def test_roundtrip_audio() -> None:
    token = uuid.uuid4().hex
    data = confirm_callback_data(token, FormatKind.AUDIO)
    assert parse_confirm_callback(data) == (token, FormatKind.AUDIO, QualityKind.HD_720)


def test_roundtrip_each_quality_tier() -> None:
    token = uuid.uuid4().hex
    for quality in QualityKind:
        data = confirm_callback_data(token, FormatKind.VIDEO, quality)
        assert parse_confirm_callback(data) == (token, FormatKind.VIDEO, quality)


def test_1080_survives_the_roundtrip_distinctly() -> None:
    # A roundtrip test that only ever used the default tier would pass
    # against a parser that ignored the code entirely.
    token = uuid.uuid4().hex
    data = confirm_callback_data(token, FormatKind.VIDEO, QualityKind.HD_1080)
    assert data.endswith(":v1080")
    assert parse_confirm_callback(data)[2] is QualityKind.HD_1080


def test_audio_payload_carries_no_tier() -> None:
    # An mp3 button must not imply a quality choice that has no effect.
    token = uuid.uuid4().hex
    for quality in QualityKind:
        assert confirm_callback_data(token, FormatKind.AUDIO, quality).endswith(":a")


# --- historical payload forms (risk: a button rendered by an old deploy) ---


def test_legacy_bare_token_defaults_to_video_720() -> None:
    # Pre-Day-11A buttons had no suffix at all.
    token = uuid.uuid4().hex
    assert parse_confirm_callback(CB_CONFIRM_PREFIX + token) == (
        token,
        FormatKind.VIDEO,
        QualityKind.HD_720,
    )


def test_tierless_video_code_degrades_to_720() -> None:
    """The Day 11A video button was ``dl:<token>:v`` — no tier.

    720 is not an arbitrary fallback here: it is what that button
    actually downloaded when it was rendered (the stage-1 default), so an
    old card delivers what it promised instead of silently upgrading the
    user to 1080p (a bigger file, possibly over the delivery limit).
    """
    token = uuid.uuid4().hex
    assert parse_confirm_callback(f"{CB_CONFIRM_PREFIX}{token}:v") == (
        token,
        FormatKind.VIDEO,
        QualityKind.HD_720,
    )


def test_unknown_code_falls_back_to_video_720() -> None:
    # Malformed or forged suffix: degrade, never raise inside the handler.
    token = uuid.uuid4().hex
    for bad in ("z", "v999", "v0", "", "video"):
        assert parse_confirm_callback(f"{CB_CONFIRM_PREFIX}{token}:{bad}") == (
            token,
            FormatKind.VIDEO,
            QualityKind.HD_720,
        )


# --- budget and routing ------------------------------------------------------


def test_all_payloads_within_telegram_budget() -> None:
    token = uuid.uuid4().hex
    payloads = [
        confirm_callback_data(token, FormatKind.AUDIO),
        *(confirm_callback_data(token, FormatKind.VIDEO, q) for q in QualityKind),
        CB_QUALITY_PREFIX + token,
        CB_BACK_PREFIX + token,
        CB_CANCEL_PREFIX + token,
    ]
    for data in payloads:
        assert len(data.encode("utf-8")) <= 64, data


def test_longest_payload_is_the_documented_41_bytes() -> None:
    token = uuid.uuid4().hex
    longest = max(
        (confirm_callback_data(token, FormatKind.VIDEO, q) for q in QualityKind),
        key=len,
    )
    assert len(longest.encode("utf-8")) == 41


def test_confirm_prefix_preserved_for_router_match() -> None:
    token = uuid.uuid4().hex
    assert confirm_callback_data(token, FormatKind.AUDIO).startswith(CB_CONFIRM_PREFIX)
    for quality in QualityKind:
        data = confirm_callback_data(token, FormatKind.VIDEO, quality)
        assert data.startswith(CB_CONFIRM_PREFIX)


def test_no_callback_prefix_shadows_another() -> None:
    """Routers filter with ``startswith``, so if one prefix were a prefix
    of another, whichever router is registered first would swallow the
    other's taps — a bug that appears only in the live bot and depends on
    include_router order. Adding a new prefix must fail here instead.
    """
    prefixes = [
        CB_CONFIRM_PREFIX,
        CB_CANCEL_PREFIX,
        CB_QUALITY_PREFIX,
        CB_BACK_PREFIX,
        CB_LANG_PREFIX,
        CB_FLOW_DOWNLOAD,
        CB_FLOW_HELP,
    ]
    assert len(set(prefixes)) == len(prefixes)
    for a in prefixes:
        for b in prefixes:
            if a is not b:
                assert not a.startswith(b), f"{a!r} is shadowed by {b!r}"
