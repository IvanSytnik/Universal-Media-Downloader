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

Everything else is unchanged: URLs are stashed under a short token
(callback_data can't hold a URL), ✅ resolves the token and calls the same
RequestDownloadUseCase /download uses, the Application layer is untouched.
"""

from __future__ import annotations

from collections.abc import Callable
from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram_i18n import I18nContext
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.config.settings import Settings
from src.domain.exceptions import ExtractionError, UnsupportedURLError
from src.domain.interfaces.preview_context_store import PreviewContextStorePort
from src.domain.interfaces.rate_limiter import RateLimiterPort
from src.domain.value_objects.url_validation import validate_url_against_allowlist
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.presentation.telegram.formatting import (
    format_help,
    format_preview,
    format_retry_after,
)
from src.presentation.telegram.keyboards import (
    BTN_KEY_DOWNLOAD,
    BTN_KEY_HELP,
    CB_CANCEL_PREFIX,
    CB_CONFIRM_PREFIX,
    CB_FLOW_DOWNLOAD,
    CB_FLOW_HELP,
    preview_confirm_keyboard,
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
) -> None:
    """Shared preview step for both entry points. Validation runs BEFORE
    the rate-limit check so a typo doesn't burn a preview slot."""
    try:
        validated_url = validate_url_against_allowlist(url, settings.allowed_domains_set)
    except UnsupportedURLError as exc:
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

    use_case = PreviewDownloadUseCase(YtDlpDownloader())
    try:
        preview = await use_case.execute(validated_url)
    except UnsupportedURLError as exc:
        await status_message.edit_text(i18n.get("error-bad-url", reason=html_escape(str(exc))))
        return
    except ExtractionError as exc:
        await status_message.edit_text(
            i18n.get("error-extraction-failed", reason=html_escape(str(exc)))
        )
        return

    token = await preview_store.save(validated_url)
    logger.info("flow_preview_shown", url=validated_url, token=token)

    await status_message.edit_text(
        format_preview(i18n, preview),
        reply_markup=preview_confirm_keyboard(i18n, token),
    )


# --- Entry point 1: main-menu buttons (text-routed, localized) ------------


@router.message(_button_matcher(BTN_KEY_DOWNLOAD))
async def handle_download_reply_button(
    message: Message, i18n: I18nContext, state: FSMContext
) -> None:
    await state.set_state(DownloadFlow.waiting_for_url)
    await message.answer(i18n.get("flow-send-url"))


@router.message(_button_matcher(BTN_KEY_HELP))
async def handle_help_reply_button(
    message: Message, i18n: I18nContext, settings: Settings
) -> None:
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
) -> None:
    await state.clear()
    await _show_preview(
        message, (message.text or "").strip(), i18n, settings, preview_store, rate_limiter
    )


# --- Entry point 2: a plain URL pasted without any button/command ---------


@router.message(F.text, lambda m: _looks_like_url(m.text or ""))
async def handle_plain_url(
    message: Message,
    i18n: I18nContext,
    settings: Settings,
    preview_store: PreviewContextStorePort,
    rate_limiter: RateLimiterPort,
) -> None:
    await _show_preview(
        message, (message.text or "").strip(), i18n, settings, preview_store, rate_limiter
    )


# --- Preview card buttons ---------------------------------------------------


@router.callback_query(F.data.startswith(CB_CONFIRM_PREFIX))
async def handle_confirm_download(
    callback: CallbackQuery,
    i18n: I18nContext,
    session_factory: async_sessionmaker[AsyncSession],
    arq_pool: ArqRedis,
    preview_store: PreviewContextStorePort,
    settings: Settings,
    rate_limiter: RateLimiterPort,
) -> None:
    token = (callback.data or "")[len(CB_CONFIRM_PREFIX):]
    url = await preview_store.get(token)

    if url is None:
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

    await preview_store.delete(token)

    telegram_id = callback.from_user.id

    async with session_scope(session_factory) as session:
        use_case = RequestDownloadUseCase(
            user_repository=SqlAlchemyUserRepository(session),
            download_request_repository=SqlAlchemyDownloadRequestRepository(session),
            task_queue=ArqTaskQueue(arq_pool),
        )
        try:
            request = await use_case.execute(telegram_id, url)
        except UnsupportedURLError as exc:
            await callback.answer(
                i18n.get("error-bad-url", reason=str(exc)[:150]), show_alert=True
            )
            return

    logger.info("flow_download_confirmed", request_id=str(request.id), telegram_id=telegram_id)

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
    token = (callback.data or "")[len(CB_CANCEL_PREFIX):]
    await preview_store.delete(token)

    if isinstance(callback.message, Message):
        current_text = callback.message.text or ""
        await callback.message.edit_text(html_escape(current_text) + i18n.get("flow-cancelled"))
    await callback.answer()
