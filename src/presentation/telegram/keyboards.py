"""Inline keyboards — pure builders, no I/O, trivially unit-testable.

callback_data conventions (Telegram hard limit: 64 bytes):
- "flow:download"        — main-menu "Скачать" button
- "flow:help"            — main-menu "Помощь" button
- "dl:<token>"           — confirm download of a previewed URL;
                           <token> is a 32-char hex from
                           PreviewContextStorePort, so total is 35 bytes
- "cancel:<token>"       — dismiss a preview
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

CB_FLOW_DOWNLOAD = "flow:download"
CB_FLOW_HELP = "flow:help"
CB_CONFIRM_PREFIX = "dl:"
CB_CANCEL_PREFIX = "cancel:"

# Reply-keyboard button labels (Day 8). Handlers match on exact text,
# so these constants are the single source of truth for both the
# keyboard builder and the handlers — never inline these strings.
BTN_DOWNLOAD = "⬇️ Скачать"
BTN_HELP = "ℹ️ Помощь"


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent bottom keyboard (Day 8).

    Replaces the Day 7 inline main menu in /start: a reply keyboard is
    always visible, so the user never has to scroll back to the /start
    message to find the buttons. Inline keyboards remain where they
    belong — attached to preview cards. The old flow:* callback
    handlers are kept so buttons under previously sent /start messages
    keep working.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=BTN_DOWNLOAD),
                KeyboardButton(text=BTN_HELP),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Пришли ссылку на видео…",
    )


def preview_confirm_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Скачать", callback_data=CB_CONFIRM_PREFIX + token
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=CB_CANCEL_PREFIX + token
                ),
            ]
        ]
    )
