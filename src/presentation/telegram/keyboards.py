"""Keyboards — pure builders. Day 9: labels come from i18n.

callback_data conventions (Telegram hard limit: 64 bytes) are
language-independent by design — only the *visible label* is localized,
the routing payload stays constant:
- "flow:download" / "flow:help"  — legacy inline main-menu buttons
- "dl:<token>:<code>"            — confirm download of a previewed URL.
                                   <code> is "a" (audio/mp3) or "v720" /
                                   "v1080" (video at a quality tier).
                                   Budget: 3 + 32 (uuid4 hex) + 1 + 5 =
                                   41 bytes, under 64.
- "q:<token>"                    — open the quality picker (step 2).
                                   Budget: 2 + 32 = 34 bytes.
- "back:<token>"                 — return from the picker to step 1.
                                   Budget: 5 + 32 = 37 bytes.
- "cancel:<token>"               — dismiss a preview

Day 11C stage 4 — two-step video flow. Tapping "Video" no longer starts
a download; it swaps the card's markup for the quality picker (720/1080/
back). MP3 still downloads immediately, because quality is meaningless
for an extracted audio track.

Prefix hygiene: "q:" and "back:" are NOT prefixes of "dl:", "cancel:",
"lang:", or "flow:", and none of those is a prefix of them, so no
router's ``startswith`` filter can swallow another's payload regardless
of the order routers are registered. Pinned by a test.

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
from src.domain.value_objects.quality_kind import QualityKind

CB_FLOW_DOWNLOAD = "flow:download"
CB_FLOW_HELP = "flow:help"
CB_CONFIRM_PREFIX = "dl:"
CB_CANCEL_PREFIX = "cancel:"
# Day 11C stage 4: the two extra steps of the video flow.
CB_QUALITY_PREFIX = "q:"
CB_BACK_PREFIX = "back:"
# Day 9.2: language picker. Payload is the target locale code, which is
# language-independent (unlike the button label), so it survives the
# user's current UI language just like the other callback_data above.
CB_LANG_PREFIX = "lang:"

# Day 11A: one-char format codes in the confirm callback payload. Short
# on purpose (callback_data budget), and independent of UI language.
_FMT_CODE_VIDEO = "v"
_FMT_CODE_AUDIO = "a"

# Day 11C stage 4: video codes carry the tier ("v720"/"v1080"). The tier
# suffix is the enum's own height, so adding a tier needs no table here —
# QualityKind stays the single tier→height mapping (see quality_kind.py).
_VIDEO_CODES = {f"{_FMT_CODE_VIDEO}{q.max_height}": q for q in QualityKind}
_QUALITY_TO_CODE = {q: f"{_FMT_CODE_VIDEO}{q.max_height}" for q in QualityKind}

BTN_KEY_QUALITY_720 = "btn-quality-720"
BTN_KEY_QUALITY_1080 = "btn-quality-1080"
BTN_KEY_BACK = "btn-back"
_QUALITY_LABEL_KEYS = {
    QualityKind.HD_720: BTN_KEY_QUALITY_720,
    QualityKind.HD_1080: BTN_KEY_QUALITY_1080,
}

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


def confirm_callback_data(
    token: str,
    format_kind: FormatKind,
    quality_kind: QualityKind = QualityKind.HD_720,
) -> str:
    """Build the confirm payload: ``dl:<token>:<code>``.

    Audio ignores the tier entirely and stays a bare "a" — carrying a
    quality suffix on an mp3 button would imply a choice that has no
    effect.
    """
    if format_kind is FormatKind.AUDIO:
        return f"{CB_CONFIRM_PREFIX}{token}:{_FMT_CODE_AUDIO}"
    return f"{CB_CONFIRM_PREFIX}{token}:{_QUALITY_TO_CODE[quality_kind]}"


def parse_confirm_callback(data: str) -> tuple[str, FormatKind, QualityKind]:
    """Parse a confirm payload into (token, format_kind, quality_kind).

    Every historical form of this button is accepted, because inline
    buttons rendered by an older deploy keep sitting in users' chats long
    after an upgrade — a callback is not a request we control the age of:

    * ``dl:<token>:v720`` / ``:v1080`` — Day 11C stage 4, explicit tier.
    * ``dl:<token>:a``                 — mp3; tier is irrelevant, so the
                                         default is returned and ignored
                                         downstream.
    * ``dl:<token>:v``                 — Day 11A video button with NO
                                         tier. Degrades to HD_720, which
                                         is exactly what that button did
                                         when it was rendered (stage 1's
                                         default), so an old card
                                         downloads what it promised.
    * ``dl:<token>``                   — pre-Day-11A bare form → video,
                                         HD_720.

    Anything unrecognized degrades to (VIDEO, HD_720) rather than
    raising: a malformed or forged payload must not crash the handler.
    """
    body = data[len(CB_CONFIRM_PREFIX) :]
    token, sep, code = body.rpartition(":")
    if not sep:
        # Legacy bare "dl:<token>" — rpartition put everything in `code`.
        return body, FormatKind.VIDEO, QualityKind.HD_720
    if code == _FMT_CODE_AUDIO:
        return token, FormatKind.AUDIO, QualityKind.HD_720
    # "v" (tierless, Day 11A) and anything unknown land on the default.
    return token, FormatKind.VIDEO, _VIDEO_CODES.get(code, QualityKind.HD_720)


def preview_confirm_keyboard(i18n: I18nContext, token: str) -> InlineKeyboardMarkup:
    """Preview card actions — STEP 1 of the video flow.

    Day 11A made the single "Download" button two (video / mp3). Day 11C
    stage 4 changes what the video button DOES: it no longer starts a
    download, it opens the quality picker ("q:<token>"), which replaces
    this markup in place. MP3 still downloads immediately — quality is
    meaningless for an extracted audio track, so asking would be a step
    with one real answer.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get("btn-confirm-video"),
                    callback_data=CB_QUALITY_PREFIX + token,
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


def quality_picker_keyboard(i18n: I18nContext, token: str) -> InlineKeyboardMarkup:
    """STEP 2 — the tiers, plus a way back.

    Built by iterating QualityKind rather than listing 720/1080 by hand,
    so a new tier shows up here automatically (it only needs a label key).
    "Back" returns to step 1 with the SAME token: nothing has been
    consumed yet, so backing out is free — the token is only claimed when
    a tier is actually tapped (see the handler's use of ``pop``).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=i18n.get(_QUALITY_LABEL_KEYS[quality]),
                    callback_data=confirm_callback_data(token, FormatKind.VIDEO, quality),
                )
                for quality in QualityKind
            ],
            [
                InlineKeyboardButton(
                    text=i18n.get(BTN_KEY_BACK), callback_data=CB_BACK_PREFIX + token
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
