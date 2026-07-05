"""Guided download flow (Day 7): buttons → link → preview → confirm.

Two entry points converge on the same preview step:
1. Tap "⬇️ Скачать" → bot asks for a link → next message is the URL.
2. Just paste a URL as a plain message (no button, no command) — the
   power-user shortcut.

Either way the user gets a preview card with ✅/❌ buttons. The URL is
stashed in PreviewContextStore under a short token (callback_data can't
hold a URL — 64-byte limit), and ✅ resolves the token back and calls
the same RequestDownloadUseCase that /download uses. The Application
layer is untouched by this feature — everything here is Presentation
plus one small infrastructure adapter, exactly as the Dependency Rule
wants it.

The legacy /preview and /download commands keep working unchanged.
"""

from __future__ import annotations

from html import escape as html_escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from arq import ArqRedis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.application.use_cases.request_download import RequestDownloadUseCase
from src.config.settings import Settings
from src.domain.exceptions import ExtractionError, UnsupportedURLError
from src.domain.interfaces.preview_context_store import PreviewContextStorePort
from src.domain.value_objects.url_validation import validate_url_against_allowlist
from src.infrastructure.database.engine import session_scope
from src.infrastructure.database.repositories.download_request_repository import (
    SqlAlchemyDownloadRequestRepository,
)
from src.infrastructure.database.repositories.user_repository import SqlAlchemyUserRepository
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.infrastructure.queue.arq_task_queue import ArqTaskQueue
from src.presentation.telegram.formatting import format_preview
from src.presentation.telegram.keyboards import (
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

_HELP_TEXT = (
    "Я скачиваю видео по ссылке с поддерживаемых сайтов "
    "(YouTube, TikTok, Instagram, Twitter/X, VK и другие).\n\n"
    "Как пользоваться:\n"
    "1. Нажми «⬇️ Скачать» или просто пришли ссылку сообщением.\n"
    "2. Я покажу превью — название, автора, длительность.\n"
    "3. Нажми «✅ Скачать» под превью, и я пришлю файл сюда же.\n\n"
    "Команды:\n"
    "/preview ссылка — только информация о видео\n"
    "/download ссылка — скачать сразу, без превью"
)


def _looks_like_url(text: str) -> bool:
    """Cheap Presentation-level routing check, NOT validation.

    Decides only whether a plain message should enter the download flow
    at all; real validation (structure + allowlist) happens in
    `_show_preview` via validate_url_against_allowlist. Kept deliberately
    dumb so a message like "привет" never triggers a validation error
    reply — the bot just ignores non-URL chatter.
    """
    stripped = text.strip()
    return stripped.startswith(("http://", "https://"))


async def _show_preview(
    message: Message,
    url: str,
    settings: Settings,
    preview_store: PreviewContextStorePort,
) -> None:
    """Shared preview step for both entry points (button flow and
    direct paste). Validates against the allowlist, fetches metadata,
    replies with a preview card + confirm/cancel buttons.
    """
    try:
        validated_url = validate_url_against_allowlist(url, settings.allowed_domains_set)
    except UnsupportedURLError as exc:
        await message.answer(f"Некорректная ссылка: {html_escape(str(exc))}")
        return

    status_message = await message.answer("🔍 Получаю информацию о видео…")

    use_case = PreviewDownloadUseCase(YtDlpDownloader())
    try:
        preview = await use_case.execute(validated_url)
    except UnsupportedURLError as exc:
        await status_message.edit_text(f"Некорректная ссылка: {html_escape(str(exc))}")
        return
    except ExtractionError as exc:
        await status_message.edit_text(
            f"Не удалось получить информацию: {html_escape(str(exc))}"
        )
        return

    token = await preview_store.save(validated_url)
    logger.info("flow_preview_shown", url=validated_url, token=token)

    await status_message.edit_text(
        format_preview(preview),
        reply_markup=preview_confirm_keyboard(token),
    )


# --- Entry point 1: main-menu buttons -------------------------------------


@router.callback_query(F.data == CB_FLOW_DOWNLOAD)
async def handle_download_button(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(DownloadFlow.waiting_for_url)
    if isinstance(callback.message, Message):
        await callback.message.answer(
            "Пришли ссылку на видео — покажу превью перед скачиванием."
        )
    await callback.answer()


@router.callback_query(F.data == CB_FLOW_HELP)
async def handle_help_button(callback: CallbackQuery) -> None:
    if isinstance(callback.message, Message):
        await callback.message.answer(_HELP_TEXT)
    await callback.answer()


@router.message(DownloadFlow.waiting_for_url, F.text)
async def handle_url_in_state(
    message: Message,
    state: FSMContext,
    settings: Settings,
    preview_store: PreviewContextStorePort,
) -> None:
    # Clear the state unconditionally BEFORE processing: whatever the
    # user sent, they are out of "waiting" mode — no trap where every
    # subsequent message keeps producing "Некорректная ссылка".
    await state.clear()
    await _show_preview(message, (message.text or "").strip(), settings, preview_store)


# --- Entry point 2: a plain URL pasted without any button/command ---------


@router.message(F.text, lambda m: _looks_like_url(m.text or ""))
async def handle_plain_url(
    message: Message,
    settings: Settings,
    preview_store: PreviewContextStorePort,
) -> None:
    # This router is included LAST in the dispatcher (see bot.py), so
    # commands like "/preview https://..." never reach here — command
    # handlers win first. Only bare URLs land in this handler.
    await _show_preview(message, (message.text or "").strip(), settings, preview_store)


# --- Preview card buttons ---------------------------------------------------


@router.callback_query(F.data.startswith(CB_CONFIRM_PREFIX))
async def handle_confirm_download(
    callback: CallbackQuery,
    session_factory: async_sessionmaker[AsyncSession],
    arq_pool: ArqRedis,
    preview_store: PreviewContextStorePort,
) -> None:
    token = (callback.data or "")[len(CB_CONFIRM_PREFIX):]
    url = await preview_store.get(token)

    if url is None:
        # Expired (TTL) or already consumed (double-tap) — tell the
        # user gently instead of failing silently or re-downloading.
        await callback.answer(
            "Превью устарело — пришли ссылку ещё раз.", show_alert=True
        )
        return

    # Consume the token first: a second tap on ✅ while the first one is
    # still processing must not enqueue a duplicate download.
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
                f"Некорректная ссылка: {str(exc)[:150]}", show_alert=True
            )
            return

    logger.info(
        "flow_download_confirmed",
        request_id=str(request.id),
        telegram_id=telegram_id,
        token=token,
    )

    if isinstance(callback.message, Message):
        # Remove the buttons so the card can't be tapped again, and
        # append the status right into the same message.
        current_text = callback.message.text or ""
        await callback.message.edit_text(
            html_escape(current_text)
            + "\n\n⏳ Скачивание начато — пришлю файл сюда же, когда будет готово.",
        )
    await callback.answer()


@router.callback_query(F.data.startswith(CB_CANCEL_PREFIX))
async def handle_cancel_download(
    callback: CallbackQuery,
    preview_store: PreviewContextStorePort,
) -> None:
    token = (callback.data or "")[len(CB_CANCEL_PREFIX):]
    await preview_store.delete(token)

    if isinstance(callback.message, Message):
        current_text = callback.message.text or ""
        await callback.message.edit_text(html_escape(current_text) + "\n\n❌ Отменено.")
    await callback.answer()
