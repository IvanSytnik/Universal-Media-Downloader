"""Guided download flow (Day 7): buttons → link → preview → confirm.

Day 9 — localization touches exactly one thing in the routing logic here,
and it's worth being explicit about it (it's the only place i18n leaks
into control flow, per the Day 9 architecture discussion):

The two main-menu buttons are a *reply* keyboard, which Telegram gives no
callback_data — they can only be routed by their visible TEXT. Once that
text is localized, "⬇️ Скачать" and "⬇️ Download" are the same logical
button. A user can also still have an old keyboard (rendered in a
previous locale) at the bottom of the chat after switching languages. So
matching a single constant string is wrong; we match against the SET of
all translations of the button key, across every enabled locale. That
set is built once at startup (i18n.collect_button_translations) and
injected into handlers as ``button_translations`` — see bot.py/main.py.

Day 10 — two DISTINCT origins of ``UnsupportedURLError`` are kept apart:
1. Our own allowlist validator (validate_url_against_allowlist) raises it
   BEFORE yt-dlp runs, with a safe, meaningful ``reason`` — shown via the
   ``error-bad-url`` key (reason preserved: it's our text, not yt-dlp's).
2. The downloader/classifier raises categorized errors (including
   ``UnsupportedURLError`` for a genuinely unsupported site) — shown via
   ``format_download_error``, which reads ``error_key`` and never leaks
   raw text (bug #6).
Mixing these up would either lose our helpful validation reason or leak
yt-dlp diagnostics — so the two catch sites stay separate.

Day 11A — the preview card now offers two confirm buttons (video / mp3).
Both share one token; the chosen format is encoded in the callback
payload and parsed by ``parse_confirm_callback``. The parsed
``DownloadSpec`` (Day 11C v2) is threaded into RequestDownloadUseCase, which persists it
on the request so the worker downloads the right thing. Everything else
about the confirm path (token lookup, rate limit ordering, stale-preview
handling) is unchanged.

Everything else is unchanged: URLs are stashed under a short token
(callback_data can't hold a URL), the confirm button resolves the token
and calls the same RequestDownloadUseCase /download uses, the Application
layer contract is the same bar the new optional argument.

Day 11C (v2) — every keyboard on the card is rendered from
``FormatPolicy.offered_choices`` over the stored PreviewContext (the
extractor and short side the preview OBSERVED), so ``q:``/``back:``
re-derive the buttons on each tap instead of trusting what the previous
markup showed: a kill-switch flipped while the card sat in the chat is
reflected on the next tap. ``q:`` on a card whose source no longer has a
quality step just re-renders step 1.

Day 11B — real-time progress needs a concrete (chat_id, message_id) to
edit, so ``handle_confirm_download`` now requires ``callback.message`` to
be a real ``Message`` (not None/inaccessible) before enqueueing at all —
those coordinates come straight from the preview card that's already on
screen, no extra lookup.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram_i18n import I18nContext

from src.application.policies.format_policy import FormatPolicy, OfferedChoices
from src.config.settings import Settings
from src.domain.exceptions import (
    DownloadEnqueueError,
    ExtractionError,
    FormatNotAllowedError,
    UnsupportedURLError,
)
from src.domain.interfaces.preview_context_store import PreviewContextStorePort
from src.domain.interfaces.rate_limiter import RateLimiterPort
from src.domain.value_objects.preview_context import PreviewContext
from src.domain.value_objects.url_validation import validate_url_against_allowlist
from src.presentation.telegram.dependencies import UseCaseProvider
from src.presentation.telegram.formatting import (
    format_download_error,
    format_help,
    format_preview,
    format_retry_after,
)
from src.presentation.telegram.keyboards import (
    BTN_KEY_DOWNLOAD,
    BTN_KEY_HELP,
    CB_BACK_PREFIX,
    CB_CANCEL_PREFIX,
    CB_CONFIRM_PREFIX,
    CB_FLOW_DOWNLOAD,
    CB_FLOW_HELP,
    CB_QUALITY_PREFIX,
    parse_confirm_callback,
    preview_confirm_keyboard,
    quality_picker_keyboard,
)
from src.presentation.telegram.states import DownloadFlow
from src.shared.logging import get_logger

router = Router(name="download_flow")
logger = get_logger(__name__)


def _looks_like_url(text: str) -> bool:
    """Cheap Presentation-level routing check, NOT validation."""
    stripped = text.strip()
    return stripped.startswith(("http://", "https://"))


def _button_matcher(
    button_key: str,
) -> Callable[[Message, dict[str, frozenset[str]]], bool]:
    """Build an aiogram filter that matches a message whose text is ANY
    translation of ``button_key`` (decision 3A).

    ``button_translations`` is injected by the dispatcher (workflow data);
    the filter reads the precomputed set for this key. Falls back to an
    empty set if it's somehow absent, which simply means "no match" — a
    safe default that degrades to ignoring the message rather than
    crashing.
    """

    def _matches(message: Message, button_translations: dict[str, frozenset[str]]) -> bool:
        texts = button_translations.get(button_key, frozenset())
        return message.text is not None and message.text in texts

    return _matches


async def _show_preview(
    message: Message,
    url: str,
    i18n: I18nContext,
    settings: Settings,
    preview_store: PreviewContextStorePort,
    rate_limiter: RateLimiterPort,
    use_cases: UseCaseProvider,
    format_policy: FormatPolicy,
) -> None:
    """Shared preview step for both entry points. Validation runs BEFORE
    the rate-limit check so a typo doesn't burn a preview slot."""
    try:
        validated_url = validate_url_against_allowlist(
            url, settings.allowed_domains_set, settings.blocked_domains_set
        )
    except UnsupportedURLError as exc:
        # Origin 1: OUR validator. `reason` is our own safe text — keep it.
        await message.answer(i18n.get("error-bad-url", reason=html_escape(str(exc))))
        return

    if message.from_user is not None:
        verdict = await rate_limiter.acquire(
            key=f"preview:{message.from_user.id}",
            limit=settings.rate_limit_previews_per_minute,
            window_seconds=60,
        )
        if not verdict.allowed:
            logger.info("preview_rate_limited", telegram_id=message.from_user.id)
            await message.answer(format_retry_after(i18n, verdict.retry_after_seconds))
            return

    status_message = await message.answer(i18n.get("preview-fetching"))

    try:
        preview = await use_cases.preview_download().execute(validated_url)
    except (ExtractionError, UnsupportedURLError) as exc:
        # Origin 2: the downloader/classifier. Categorized; render via
        # error_key, never raw text.
        await status_message.edit_text(format_download_error(i18n, exc))
        return

    # Day 11C (v2): store what the preview OBSERVED next to the URL; the
    # buttons later act on this, never on anything the callback claims.
    context = PreviewContext.from_preview(preview)
    token = await preview_store.save(context)
    logger.info(
        "flow_preview_shown",
        url=validated_url,
        token=token,
        extractor_key=preview.extractor_key,
        max_compatible_short_side=preview.max_compatible_short_side,
    )

    await status_message.edit_text(
        format_preview(i18n, preview),
        reply_markup=preview_confirm_keyboard(i18n, token, _choices(format_policy, context)),
    )


def _choices(format_policy: FormatPolicy, context: PreviewContext) -> OfferedChoices:
    return format_policy.offered_choices(context.extractor_key, context.max_compatible_short_side)


# --- Entry point 1: main-menu buttons (text-routed, localized) ------------


@router.message(_button_matcher(BTN_KEY_DOWNLOAD))
async def handle_download_reply_button(
    message: Message, i18n: I18nContext, state: FSMContext
) -> None:
    await state.set_state(DownloadFlow.waiting_for_url)
    await message.answer(i18n.get("flow-send-url"))


@router.message(_button_matcher(BTN_KEY_HELP))
async def handle_help_reply_button(message: Message, i18n: I18nContext, settings: Settings) -> None:
    await message.answer(format_help(i18n, settings))


@router.callback_query(F.data == CB_FLOW_DOWNLOAD)
async def handle_download_button(
    callback: CallbackQuery, i18n: I18nContext, state: FSMContext
) -> None:
    await state.set_state(DownloadFlow.waiting_for_url)
    if isinstance(callback.message, Message):
        await callback.message.answer(i18n.get("flow-send-url"))
    await callback.answer()


@router.callback_query(F.data == CB_FLOW_HELP)
async def handle_help_button(
    callback: CallbackQuery, i18n: I18nContext, settings: Settings
) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(format_help(i18n, settings))
    await callback.answer()


@router.message(DownloadFlow.waiting_for_url, F.text)
async def handle_url_in_state(
    message: Message,
    state: FSMContext,
    i18n: I18nContext,
    settings: Settings,
    preview_store: PreviewContextStorePort,
    rate_limiter: RateLimiterPort,
    use_cases: UseCaseProvider,
    format_policy: FormatPolicy,
) -> None:
    await state.clear()
    await _show_preview(
        message,
        (message.text or "").strip(),
        i18n,
        settings,
        preview_store,
        rate_limiter,
        use_cases,
        format_policy,
    )


# --- Entry point 2: a plain URL pasted without any button/command ---------


@router.message(F.text, lambda m: _looks_like_url(m.text or ""))
async def handle_plain_url(
    message: Message,
    i18n: I18nContext,
    settings: Settings,
    preview_store: PreviewContextStorePort,
    rate_limiter: RateLimiterPort,
    use_cases: UseCaseProvider,
    format_policy: FormatPolicy,
) -> None:
    await _show_preview(
        message,
        (message.text or "").strip(),
        i18n,
        settings,
        preview_store,
        rate_limiter,
        use_cases,
        format_policy,
    )


# --- Preview card buttons ---------------------------------------------------


@router.callback_query(F.data.startswith(CB_QUALITY_PREFIX))
async def handle_open_quality_picker(
    callback: CallbackQuery,
    i18n: I18nContext,
    preview_store: PreviewContextStorePort,
    format_policy: FormatPolicy,
) -> None:
    """Step 1 -> 2: swap the card's markup for the tier picker.

    The token is only READ here, never claimed: the user may still tap
    Back, and a picker that consumed the token would strand them on a
    dead card. It IS checked, though — showing tiers for an expired
    preview would just move the failure one tap later, after the user
    has made a choice, which is a worse place to learn about it.

    The tiers come from the policy over the stored context, not from the
    payload; if there is no quality step (any more — video disabled since
    the card was rendered, or a forged ``q:``), step 1 is re-rendered.
    """
    token = (callback.data or "")[len(CB_QUALITY_PREFIX) :]
    context = await preview_store.get(token)
    if context is None:
        await callback.answer(i18n.get("flow-preview-stale"), show_alert=True)
        return

    choices = _choices(format_policy, context)
    if isinstance(callback.message, Message):
        # Only the markup changes — the preview text stays put, so the
        # card doesn't flicker and nothing needs re-escaping.
        markup = (
            quality_picker_keyboard(
                i18n, token, choices.video_tiers, context.max_compatible_short_side
            )
            if choices.has_quality_step
            else preview_confirm_keyboard(i18n, token, choices)
        )
        await callback.message.edit_reply_markup(reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith(CB_BACK_PREFIX))
async def handle_back_to_format(
    callback: CallbackQuery,
    i18n: I18nContext,
    preview_store: PreviewContextStorePort,
    format_policy: FormatPolicy,
) -> None:
    """Step 2 -> 1. Same token, nothing consumed on either leg, so the
    user can bounce between the two steps until the TTL runs out."""
    token = (callback.data or "")[len(CB_BACK_PREFIX) :]
    context = await preview_store.get(token)
    if context is None:
        await callback.answer(i18n.get("flow-preview-stale"), show_alert=True)
        return

    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=preview_confirm_keyboard(i18n, token, _choices(format_policy, context))
        )
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CONFIRM_PREFIX))
async def handle_confirm_download(
    callback: CallbackQuery,
    i18n: I18nContext,
    use_cases: UseCaseProvider,
    preview_store: PreviewContextStorePort,
    settings: Settings,
    rate_limiter: RateLimiterPort,
) -> None:
    # Day 11A: the payload carries the chosen format after the token.
    # Day 11C stage 4: for video it carries the quality tier too. The
    # parser tolerates every older form (bare "dl:<token>", tierless
    # "dl:<token>:v"), so buttons rendered before this deploy still work
    # and degrade to DEFAULT_DOWNLOAD_SPEC (720p) — what they actually did.
    token, spec = parse_confirm_callback(callback.data or "")

    # Day 11C stage 4: CLAIM the token atomically instead of get-then-
    # delete-later. This is the whole double-tap guard: two fast taps on
    # 720p used to both read the URL before either delete landed, and
    # enqueued two downloads. Now the loser gets None and falls into the
    # stale-preview branch below.
    context = await preview_store.pop(token)

    if context is None:
        await callback.answer(i18n.get("flow-preview-stale"), show_alert=True)
        return

    if not isinstance(callback.message, Message):
        # Day 11B: progress needs a concrete (chat_id, message_id) to
        # edit. An inaccessible/missing preview card means there's
        # nowhere to render it — bail out rather than enqueueing a
        # download with no target. Reuses the existing stale-preview
        # copy; this is rare enough not to warrant a dedicated key.
        await callback.answer(i18n.get("flow-preview-stale"), show_alert=True)
        return

    verdict = await rate_limiter.acquire(
        key=f"download:{callback.from_user.id}",
        limit=settings.rate_limit_downloads_per_hour,
        window_seconds=3600,
    )
    if not verdict.allowed:
        logger.info("download_rate_limited", telegram_id=callback.from_user.id)
        await callback.answer(
            format_retry_after(i18n, verdict.retry_after_seconds), show_alert=True
        )
        return

    telegram_id = callback.from_user.id
    chat_id = callback.message.chat.id
    message_id = callback.message.message_id

    async with use_cases.request_download() as use_case:
        try:
            request = await use_case.execute(
                telegram_id,
                context.url,
                spec,
                # From the stored preview, never from callback data.
                context.extractor_key,
                chat_id=chat_id,
                message_id=message_id,
            )
        except FormatNotAllowedError as exc:
            # A card rendered before the kill-switch was flipped, or a
            # forged payload. The token is already consumed — correct: the
            # card offers something we refuse, it should not stay live.
            logger.info(
                "flow_format_not_allowed",
                telegram_id=telegram_id,
                extractor_key=context.extractor_key,
                spec=repr(spec),
            )
            await callback.answer(format_download_error(i18n, exc), show_alert=True)
            return
        except UnsupportedURLError as exc:
            # Our validator again (RequestDownloadUseCase re-validates).
            await callback.answer(i18n.get("error-bad-url", reason=str(exc)[:150]), show_alert=True)
            return
        except DownloadEnqueueError as exc:
            # The card becomes the failure record: the token is spent, so
            # the buttons go (edit_text drops the keyboard) and the reason
            # stays visible under the preview. The request is already
            # failed and logged by the use case.
            current_text = callback.message.text or ""
            await callback.message.edit_text(
                html_escape(current_text)
                + i18n.get("flow-download-failed", error=format_download_error(i18n, exc))
            )
            await callback.answer()
            return

    logger.info(
        "flow_download_confirmed",
        request_id=str(request.id),
        telegram_id=telegram_id,
        spec=repr(spec),
    )

    if isinstance(callback.message, Message):
        current_text = callback.message.text or ""
        await callback.message.edit_text(
            html_escape(current_text) + i18n.get("flow-download-started")
        )
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CANCEL_PREFIX))
async def handle_cancel_download(
    callback: CallbackQuery,
    i18n: I18nContext,
    preview_store: PreviewContextStorePort,
) -> None:
    token = (callback.data or "")[len(CB_CANCEL_PREFIX) :]
    await preview_store.delete(token)

    if isinstance(callback.message, Message):
        current_text = callback.message.text or ""
        await callback.message.edit_text(html_escape(current_text) + i18n.get("flow-cancelled"))
    await callback.answer()
