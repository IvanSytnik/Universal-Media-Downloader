"""Keyboards — pure builders. Day 9: labels come from i18n.

callback_data conventions (Telegram hard limit: 64 bytes) are
language-independent by design — only the *visible label* is localized,
the routing payload stays constant:
- "flow:download" / "flow:help"  — legacy inline main-menu buttons
- "dl:<token>:<fmt>"             — confirm download of a previewed URL,
                                   where <fmt> is "v" (video) or "a"
                                   (audio/mp3). Budget: 3 + 32 (uuid4 hex)
                                   + 2 = 37 bytes, well under 64.
- "cancel:<token>"               — dismiss a preview

Day 11A note: the confirm payload gained a format suffix. The prefix
"dl:" is unchanged, so the existing ``F.data.startswith("dl:")`` router
still matches both buttons; the handler parses the suffix. A pre-Day-11
callback of the bare form "dl:<token>" (from an inline button rendered
before this deploy) is still accepted and defaults to video — see
parse_confirm_callback.

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

from src.domain.value_objects.format_kind import FormatKind

CB_FLOW_DOWNLOAD = "flow:download"
CB_FLOW_HELP = "flow:help"
CB_CONFIRM_PREFIX = "dl:"
CB_CANCEL_PREFIX = "cancel:"
# Day 9.2: language picker. Payload is the target locale code, which is
# language-independent (unlike the button label), so it survives the
# user's current UI language just like the other callback_data above.
CB_LANG_PREFIX = "lang:"

# Day 11A: one-char format codes in the confirm callback payload. Short
# on purpose (callback_data budget), and independent of UI language.
_FMT_CODE_VIDEO = "v"
_FMT_CODE_AUDIO = "a"
_CODE_TO_FORMAT = {_FMT_CODE_VIDEO: FormatKind.VIDEO, _FMT_CODE_AUDIO: FormatKind.AUDIO}
_FORMAT_TO_CODE = {FormatKind.VIDEO: _FMT_CODE_VIDEO, FormatKind.AUDIO: _FMT_CODE_AUDIO}

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


def confirm_callback_data(token: str, format_kind: FormatKind) -> str:
    """Build the confirm-button payload: ``dl:<token>:<fmt-code>``."""
    return f"{CB_CONFIRM_PREFIX}{token}:{_FORMAT_TO_CODE[format_kind]}"


def parse_confirm_callback(data: str) -> tuple[str, FormatKind]:
    """Parse a confirm callback payload into (token, format_kind).

    Accepts both the Day 11A form ``dl:<token>:<fmt>`` and the legacy
    bare form ``dl:<token>`` (an inline button rendered before this
    deploy, still sitting in a user's chat). The legacy form has no
    format code and defaults to VIDEO — the pre-Day-11 behaviour — so old
    buttons keep working instead of erroring after an upgrade.

    Unknown format codes also fall back to VIDEO rather than raising: a
    malformed/forged callback should degrade to the safe default, not
    crash the handler.
    """
    body = data[len(CB_CONFIRM_PREFIX):]
    token, sep, code = body.rpartition(":")
    if not sep:
        # Legacy bare "dl:<token>" — rpartition put everything in `code`.
        return body, FormatKind.VIDEO
    return token, _CODE_TO_FORMAT.get(code, FormatKind.VIDEO)


def preview_confirm_keyboard(i18n: I18nContext, token: str) -> InlineKeyboardMarkup:
    """Preview card actions. Day 11A: the single "Download" confirm button
    became two — video and mp3 — sharing the same token; the format is
    carried in the callback payload (see confirm_callback_data). Cancel is
    unchanged.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get("btn-confirm-video"),
                    callback_data=confirm_callback_data(token, FormatKind.VIDEO),
                ),
                InlineKeyboardButton(
                    text=i18n.get("btn-confirm-audio"),
                    callback_data=confirm_callback_data(token, FormatKind.AUDIO),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=i18n.get("btn-cancel"), callback_data=CB_CANCEL_PREFIX + token
                ),
            ],
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
