"""Keyboards — pure builders. Day 9: labels come from i18n.

callback_data conventions (Telegram hard limit: 64 bytes) are
language-independent by design — only the *visible label* is localized,
the routing payload stays constant:
- "flow:download" / "flow:help"  — legacy inline main-menu buttons
- "dl:<token>"                    — confirm download of a previewed URL
- "cancel:<token>"               — dismiss a preview

The reply-keyboard buttons have no callback_data (Telegram limitation),
so they're routed by their TEXT — which is now localized. That's why the
handlers match against the set of all translations (see
i18n.collect_button_translations / BUTTON_KEY_* below), not a single
constant string.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram_i18n import I18nContext

CB_FLOW_DOWNLOAD = "flow:download"
CB_FLOW_HELP = "flow:help"
CB_CONFIRM_PREFIX = "dl:"
CB_CANCEL_PREFIX = "cancel:"
# Day 9.2: language picker. Payload is the target locale code, which is
# language-independent (unlike the button label), so it survives the
# user's current UI language just like the other callback_data above.
CB_LANG_PREFIX = "lang:"

# FTL keys for the two text-routed reply buttons. The handlers use these
# same keys via collect_button_translations to match a tap in any locale.
BTN_KEY_DOWNLOAD = "btn-download"
BTN_KEY_HELP = "btn-help"


def main_menu_keyboard(i18n: I18nContext, locale: str | None = None) -> ReplyKeyboardMarkup:
    """Persistent bottom keyboard (Day 8), localized (Day 9).

    ``locale`` overrides the context locale — needed right after a
    /language switch (Day 9.2), where the context still holds the OLD
    locale but we want to render the menu in the newly chosen one. When
    omitted, labels resolve in the current context locale as before.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=i18n.get(BTN_KEY_DOWNLOAD, locale)),
                KeyboardButton(text=i18n.get(BTN_KEY_HELP, locale)),
            ]
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=i18n.get("flow-placeholder", locale),
    )


def preview_confirm_keyboard(i18n: I18nContext, token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get("btn-confirm"), callback_data=CB_CONFIRM_PREFIX + token
                ),
                InlineKeyboardButton(
                    text=i18n.get("btn-cancel"), callback_data=CB_CANCEL_PREFIX + token
                ),
            ]
        ]
    )


def language_picker_keyboard(i18n: I18nContext) -> InlineKeyboardMarkup:
    """Inline picker for /language. Labels are localized (via i18n), the
    callback payload is the bare locale code (CB_LANG_PREFIX + "ru"/"en"),
    so a tap resolves the same regardless of the UI language it was
    rendered in."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get("btn-lang-ru"), callback_data=CB_LANG_PREFIX + "ru"
                ),
                InlineKeyboardButton(
                    text=i18n.get("btn-lang-en"), callback_data=CB_LANG_PREFIX + "en"
                ),
            ]
        ]
    )
