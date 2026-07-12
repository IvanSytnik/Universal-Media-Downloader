"""ProcessDownloadUseCase — runs entirely inside the worker process.

Loads the DownloadRequest, drives it through pending → processing →
done/failed, and notifies the user at the end. Everything here depends
only on domain interfaces (DownloaderPort, StoragePort, NotifierPort,
ErrorLocalizerPort, the two repositories) — no arq, no aiogram
Dispatcher, no Telegram concepts beyond "a telegram_id to notify", which
is a User attribute, not a framework dependency.

Day 10 — localized, categorized failure messages. The worker has no
aiogram ``I18nContext`` (it's a separate process with no update in
flight), so it can't localize the way the Telegram handlers do. Instead
it depends on ``ErrorLocalizerPort``: the categorized downloader
exception carries a semantic ``error_key``, and the localizer turns that
key + the user's stored language into a message. This replaces the old
``f"Не удалось скачать: {exc}"`` — which was both hardcoded to one
language in the Application layer AND leaked the raw exception text to
the user (bug #6).
"""

from __future__ import annotations

from uuid import UUID

from src.domain.exceptions import (
    DownloaderError,
    ExtractionError,
    FileTooLargeError,
    NotifierError,
    UnsupportedURLError,
)
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.downloader import DownloaderPort
from src.domain.interfaces.error_localizer import ErrorLocalizerPort
from src.domain.interfaces.notifier import NotifierPort
from src.domain.interfaces.storage import StoragePort
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.download_options import DownloadOptions
from src.shared.logging import get_logger

logger = get_logger(__name__)


class ProcessDownloadUseCase:
    def __init__(
        self,
        download_request_repository: DownloadRequestRepository,
        user_repository: UserRepository,
        downloader: DownloaderPort,
        storage: StoragePort,
        notifier: NotifierPort,
        error_localizer: ErrorLocalizerPort,
        max_deliverable_file_size_bytes: int,
        download_timeout_seconds: int,
    ) -> None:
        """`max_deliverable_file_size_bytes` is injected (Day 6 fix): it
        used to be a hardcoded module-level constant here, duplicated
        with an identical constant in TelegramNotifier — a real DRY
        violation. Both now read the same value from
        `Settings.max_deliverable_file_size_bytes`, set once in
        worker_settings.py and threaded through here. This also means
        the value correctly follows whichever delivery limit is active
        (50MB via api.telegram.org, or 2000MB via a local Bot API
        server) without needing to update two places in sync.

        `error_localizer` (Day 10) resolves a categorized failure's
        ``error_key`` into a message in the user's language — see the
        module docstring for why the worker can't use aiogram-i18n
        directly.
        """
        self._download_request_repository = download_request_repository
        self._user_repository = user_repository
        self._downloader = downloader
        self._storage = storage
        self._notifier = notifier
        self._error_localizer = error_localizer
        self._max_deliverable_file_size_bytes = max_deliverable_file_size_bytes
        self._download_timeout_seconds = download_timeout_seconds

    def _localize_failure(self, exc: DownloaderError, locale: str | None) -> str:
        """Map a categorized downloader error to a localized message.

        ``FileTooLargeError`` is the one category that carries data (the
        estimated size and the limit) — those are passed to the localizer
        as Fluent arguments. Everything else resolves from ``error_key``
        alone. Any downloader error type has an ``error_key`` (the base
        classes define one), so this never falls through untranslated.
        """
        error_key = getattr(exc, "error_key", ExtractionError.error_key)
        if isinstance(exc, FileTooLargeError):
            return self._error_localizer.localize(
                error_key,
                locale,
                estimated_mb=exc.estimated_mb,
                limit_mb=exc.limit_mb,
            )
        return self._error_localizer.localize(error_key, locale)

    async def execute(self, request_id: UUID) -> None:
        request = await self._download_request_repository.get_by_id(request_id)
        if request is None:
            logger.warning("process_download_request_not_found", request_id=str(request_id))
            return

        user = await self._user_repository.get_by_id(request.user_id)
        if user is None or user.telegram_id is None:
            logger.warning("process_download_user_not_found", request_id=str(request_id))
            return

        request.mark_processing()
        await self._download_request_repository.update(request)

        output_dir = self._storage.temp_dir_for_request(request.id)
        options = DownloadOptions(
            output_dir=output_dir,
            max_filesize_bytes=self._max_deliverable_file_size_bytes,
            timeout_seconds=self._download_timeout_seconds,
        )

        try:
            file_path = await self._downloader.download(request.source_url, options)
        except (ExtractionError, UnsupportedURLError) as exc:
            logger.warning(
                "process_download_failed",
                request_id=str(request_id),
                error_key=getattr(exc, "error_key", None),
                error=str(exc),
            )
            request.mark_failed()
            await self._download_request_repository.update(request)
            await self._notifier.send_text(
                user.telegram_id, self._localize_failure(exc, user.language)
            )
            return

        try:
            await self._notifier.send_file(user.telegram_id, file_path)
        except NotifierError as exc:
            logger.warning(
                "process_download_delivery_failed", request_id=str(request_id), error=str(exc)
            )
            request.mark_failed()
            await self._download_request_repository.update(request)
            await self._notifier.send_text(
                user.telegram_id,
                self._error_localizer.localize("error-delivery-failed", user.language),
            )
            return

        request.mark_done()
        await self._download_request_repository.update(request)
        logger.info("process_download_succeeded", request_id=str(request_id))
