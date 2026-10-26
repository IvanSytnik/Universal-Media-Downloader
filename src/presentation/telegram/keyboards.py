"""Keyboards — pure builders. Day 9: labels come from i18n.

callback_data conventions (Telegram hard limit: 64 bytes) are
language-independent by design — only the *visible label* is localized,
the routing payload stays constant:
- "flow:download" / "flow:help"  — legacy inline main-menu buttons
- "dl:<token>:<code>"            — confirm download of a previewed URL.
                                   <code> is "a" (audio/mp3) or "v720" /
                                   "v1080" / "vbest" (video at a tier).
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

Day 11C (v2) — the buttons are rendered from FormatPolicy's
``OfferedChoices``, never from a fixed list: a format the kill-switch
disables is not shown, and a source with no quality worth choosing
(TikTok: h264 tops out at 720p) gets a video button that downloads
``vbest`` directly instead of opening the picker. The buttons are a hint
only — RequestDownloadUseCase enforces the policy again on every tap.

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

from src.application.policies.format_policy import DIRECT_VIDEO_SPEC, OfferedChoices
from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    VideoTier,
)

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

# Day 11C: video codes carry the tier — "v720"/"v1080" (the tier's own
# short side, so VideoTier.short_side stays the single tier→pixels
# mapping) and "vbest" for the tier that has no fixed size.
_VIDEO_CODES = {
    f"{_FMT_CODE_VIDEO}{t.short_side if t.short_side is not None else 'best'}": t for t in VideoTier
}
_TIER_TO_CODE = {t: code for code, t in _VIDEO_CODES.items()}

BTN_KEY_QUALITY_720 = "btn-quality-720"
BTN_KEY_QUALITY_1080 = "btn-quality-1080"
BTN_KEY_QUALITY_BEST = "btn-quality-best"
BTN_KEY_BACK = "btn-back"
_QUALITY_LABEL_KEYS = {
    VideoTier.P720: BTN_KEY_QUALITY_720,
    VideoTier.P1080: BTN_KEY_QUALITY_1080,
    VideoTier.BEST: BTN_KEY_QUALITY_BEST,
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


def confirm_callback_data(token: str, spec: DownloadSpec) -> str:
    """Build the confirm payload: ``dl:<token>:<code>``.

    Audio ignores the tier entirely and stays a bare "a" — carrying a
    quality suffix on an mp3 button would imply a choice that has no
    effect.
    """
    match spec:
        case AudioSpec():
            return f"{CB_CONFIRM_PREFIX}{token}:{_FMT_CODE_AUDIO}"
        case VideoSpec(tier=tier):
            return f"{CB_CONFIRM_PREFIX}{token}:{_TIER_TO_CODE[tier]}"


def parse_confirm_callback(data: str) -> tuple[str, DownloadSpec]:
    """Parse a confirm payload into (token, spec).

    Every historical form of this button is accepted, because inline
    buttons rendered by an older deploy keep sitting in users' chats long
    after an upgrade — a callback is not a request we control the age of:

    * ``dl:<token>:v720`` / ``:v1080`` / ``:vbest`` — explicit tier.
    * ``dl:<token>:a``                 — mp3.
    * ``dl:<token>:v``                 — Day 11A video button with NO
                                         tier. Degrades to the default
                                         (720p video), which
                                         is exactly what that button did
                                         when it was rendered (stage 1's
                                         default), so an old card
                                         downloads what it promised.
    * ``dl:<token>``                   — pre-Day-11A bare form → default.

    Anything unrecognized degrades to ``DEFAULT_DOWNLOAD_SPEC`` rather
    than raising: a malformed or forged payload must not crash the
    handler.
    """
    body = data[len(CB_CONFIRM_PREFIX) :]
    token, sep, code = body.rpartition(":")
    if not sep:
        # Legacy bare "dl:<token>" — rpartition put everything in `code`.
        return body, DEFAULT_DOWNLOAD_SPEC
    if code == _FMT_CODE_AUDIO:
        return token, AudioSpec()
    # "v" (tierless, Day 11A) and anything unknown land on the default.
    tier = _VIDEO_CODES.get(code)
    return token, VideoSpec(tier) if tier is not None else DEFAULT_DOWNLOAD_SPEC


def preview_confirm_keyboard(
    i18n: I18nContext, token: str, choices: OfferedChoices
) -> InlineKeyboardMarkup:
    """Preview card actions — STEP 1: ``[⬇️ Video][🎵 MP3]`` minus what
    the policy disables, then Cancel.

    The video button opens the quality picker ("q:<token>", which
    replaces this markup in place) only when ``choices`` offers a quality
    step; otherwise it downloads ``DIRECT_VIDEO_SPEC`` (vbest) at once.
    MP3 always downloads immediately — quality is meaningless for an
    extracted audio track. With both formats disabled only Cancel is
    left, so the card can still be dismissed.
    """
    actions: list[InlineKeyboardButton] = []
    if choices.video:
        actions.append(
            InlineKeyboardButton(
                text=i18n.get("btn-confirm-video"),
                callback_data=(
                    CB_QUALITY_PREFIX + token
                    if choices.has_quality_step
                    else confirm_callback_data(token, DIRECT_VIDEO_SPEC)
                ),
            )
        )
    if choices.audio:
        actions.append(
            InlineKeyboardButton(
                text=i18n.get("btn-confirm-audio"),
                callback_data=confirm_callback_data(token, AudioSpec()),
            )
        )
    cancel = [
        InlineKeyboardButton(text=i18n.get("btn-cancel"), callback_data=CB_CANCEL_PREFIX + token)
    ]
    return InlineKeyboardMarkup(inline_keyboard=[actions, cancel] if actions else [cancel])


def quality_picker_keyboard(
    i18n: I18nContext,
    token: str,
    tiers: tuple[VideoTier, ...],
    best_short_side: int | None,
) -> InlineKeyboardMarkup:
    """STEP 2 — the offered tiers (``OfferedChoices.video_tiers``), plus
    a way back.

    ``best_short_side`` labels the BEST button with the source's own top
    ("900p"), offered when the source sits between two fixed tiers.
    "Back" returns to step 1 with the SAME token: nothing has been
    consumed yet, so backing out is free — the token is only claimed when
    a tier is actually tapped (see the handler's use of ``pop``).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_tier_label(i18n, tier, best_short_side),
                    callback_data=confirm_callback_data(token, VideoSpec(tier)),
                )
                for tier in tiers
            ],
            [
                InlineKeyboardButton(
                    text=i18n.get(BTN_KEY_BACK), callback_data=CB_BACK_PREFIX + token
                ),
            ],
        ]
    )


def _tier_label(i18n: I18nContext, tier: VideoTier, best_short_side: int | None) -> str:
    if tier is VideoTier.BEST:
        # A string, not an int: Fluent would group-format 1000+ as "1,000".
        return i18n.get(BTN_KEY_QUALITY_BEST, height=str(best_short_side or ""))
    return i18n.get(_QUALITY_LABEL_KEYS[tier])


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
