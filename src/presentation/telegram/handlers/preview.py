"""/preview <url> — fetch and show media metadata. Day 9: localized.
Day 10: categorized error messages (private/geo/age/unavailable/
unsupported-media/timeout/too-large) instead of one generic string.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import Message
from aiogram_i18n import I18nContext

from src.application.use_cases.preview_download import PreviewDownloadUseCase
from src.domain.exceptions import ExtractionError, UnsupportedURLError
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.presentation.telegram.formatting import format_download_error, format_preview
from src.shared.logging import get_logger

router = Router(name="preview")
logger = get_logger(__name__)


@router.message(lambda m: m.text is not None and m.text.startswith("/preview"))
async def handle_preview(message: Message, i18n: I18nContext) -> None:
    text = message.text or ""
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(i18n.get("preview-usage"))
        return

    url = parts[1].strip()
    use_case = PreviewDownloadUseCase(YtDlpDownloader())

    try:
        preview = await use_case.execute(url)
    except (ExtractionError, UnsupportedURLError) as exc:
        # Both carry an ``error_key``; format_download_error maps it to a
        # localized message. Catching the two base types covers every
        # categorized subclass (they subclass ExtractionError) plus the
        # "site not supported" case.
        await message.answer(format_download_error(i18n, exc))
        return

    logger.info("preview_shown", url=url, title=preview.title)
    await message.answer(format_preview(i18n, preview))
