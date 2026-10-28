"""Catch-all for text no other handler took.

A link is routed only when it starts with http:// or https://
(``download_flow._looks_like_url``), so "youtube.com/watch?v=..." or any
other plain text used to get no answer at all. This router is included
LAST and answers such text with a hint instead of silence.

It never takes commands (an unknown /command stays unanswered, as
before), keyboard buttons (matched by download_flow first) or a message
sent while the guided flow waits for a URL (``waiting_for_url`` has its
own handler; ``StateFilter(None)`` keeps this one out of any state).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from aiogram_i18n import I18nContext

router = Router(name="fallback")


def is_plain_text(text: str) -> bool:
    """True for text that is not a command."""
    return not text.lstrip().startswith("/")


@router.message(StateFilter(None), F.text, lambda m: is_plain_text(m.text or ""))
async def handle_unrouted_text(message: Message, i18n: I18nContext) -> None:
    await message.answer(i18n.get("hint-send-link"))
