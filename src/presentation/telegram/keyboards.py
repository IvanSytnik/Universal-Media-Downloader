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

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

CB_FLOW_DOWNLOAD = "flow:download"
CB_FLOW_HELP = "flow:help"
CB_CONFIRM_PREFIX = "dl:"
CB_CANCEL_PREFIX = "cancel:"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬇️ Скачать", callback_data=CB_FLOW_DOWNLOAD),
                InlineKeyboardButton(text="ℹ️ Помощь", callback_data=CB_FLOW_HELP),
            ]
        ]
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
