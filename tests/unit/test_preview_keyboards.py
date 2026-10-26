"""Day 11C (v2): the preview card's keyboards are rendered from
FormatPolicy's ``OfferedChoices`` — one test per shape the policy can
produce, asserting the exact payload grid (labels are checked once, in
both locales, for the one label that takes an argument).
"""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.types import InlineKeyboardMarkup

from src.application.policies.format_policy import OfferedChoices
from src.domain.value_objects.download_spec import VideoTier
from src.presentation.telegram.i18n import create_i18n_core
from src.presentation.telegram.keyboards import (
    preview_confirm_keyboard,
    quality_picker_keyboard,
)
from tests.conftest import FakeI18n

TOKEN = "f" * 32
_STEP = (VideoTier.P720, VideoTier.P1080)


@pytest.fixture
async def i18n() -> Any:
    core = create_i18n_core()
    await core.startup()
    return FakeI18n(core, "en")


def _grid(markup: InlineKeyboardMarkup) -> list[list[str | None]]:
    return [[b.callback_data for b in row] for row in markup.inline_keyboard]


@pytest.mark.parametrize(
    ("choices", "expected"),
    [
        # Quality step offered: video opens the picker.
        (
            OfferedChoices(video=True, audio=True, video_tiers=_STEP),
            [[f"q:{TOKEN}", f"dl:{TOKEN}:a"], [f"cancel:{TOKEN}"]],
        ),
        # No quality step (TikTok, <=720p, unknown): straight to vbest.
        (
            OfferedChoices(video=True, audio=True),
            [[f"dl:{TOKEN}:vbest", f"dl:{TOKEN}:a"], [f"cancel:{TOKEN}"]],
        ),
        # DISABLED_FORMATS={"<extractor>": ["audio"]}: no MP3 button.
        (
            OfferedChoices(video=True, audio=False, video_tiers=_STEP),
            [[f"q:{TOKEN}"], [f"cancel:{TOKEN}"]],
        ),
        # Video disabled: MP3 only.
        (
            OfferedChoices(video=False, audio=True),
            [[f"dl:{TOKEN}:a"], [f"cancel:{TOKEN}"]],
        ),
        # Both disabled: the card can still be dismissed, nothing else.
        (OfferedChoices(video=False, audio=False), [[f"cancel:{TOKEN}"]]),
    ],
)
async def test_step_one_follows_offered_choices(
    i18n: Any, choices: OfferedChoices, expected: list[list[str]]
) -> None:
    assert _grid(preview_confirm_keyboard(i18n, TOKEN, choices)) == expected


async def test_picker_renders_exactly_the_offered_tiers(i18n: Any) -> None:
    kb = quality_picker_keyboard(i18n, TOKEN, _STEP, 1080)
    assert _grid(kb) == [[f"dl:{TOKEN}:v720", f"dl:{TOKEN}:v1080"], [f"back:{TOKEN}"]]
    assert [b.text for b in kb.inline_keyboard[0]] == ["720p", "1080p"]


@pytest.mark.parametrize(("locale", "label"), [("en", "900p (best)"), ("ru", "900p (лучшее)")])
async def test_best_tier_is_labelled_with_the_sources_short_side(
    i18n: Any, locale: str, label: str
) -> None:
    i18n.locale = locale
    kb = quality_picker_keyboard(i18n, TOKEN, (VideoTier.P720, VideoTier.BEST), 900)
    assert _grid(kb)[0] == [f"dl:{TOKEN}:v720", f"dl:{TOKEN}:vbest"]
    assert kb.inline_keyboard[0][1].text == label


async def test_best_label_is_not_group_formatted(i18n: Any) -> None:
    # Passed as a string on purpose: Fluent formats a number 1000+ with a
    # grouping separator ("1,040p").
    kb = quality_picker_keyboard(i18n, TOKEN, (VideoTier.P720, VideoTier.BEST), 1040)
    assert kb.inline_keyboard[0][1].text == "1040p (best)"


async def test_every_rendered_payload_fits_the_callback_budget(i18n: Any) -> None:
    markups = [
        preview_confirm_keyboard(i18n, TOKEN, OfferedChoices(video=True, audio=True)),
        preview_confirm_keyboard(
            i18n, TOKEN, OfferedChoices(video=True, audio=True, video_tiers=_STEP)
        ),
        quality_picker_keyboard(i18n, TOKEN, tuple(VideoTier), 1080),
    ]
    for markup in markups:
        for row in _grid(markup):
            for data in row:
                assert data is not None and len(data.encode("utf-8")) <= 64, data
