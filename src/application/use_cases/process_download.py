"""ProcessDownloadUseCase — runs entirely inside the worker process.

Loads the DownloadRequest, drives it through pending → processing →
done/failed, and notifies the user at the end. Everything here depends
only on domain interfaces (DownloaderPort, StoragePort, NotifierPort,
the two repositories) — no arq, no aiogram Dispatcher, no Telegram
concepts beyond "a telegram_id to notify", which is a User attribute,
not a framework dependency.
"""

from __future__ import annotations

from uuid import UUID

from src.domain.exceptions import ExtractionError, NotifierError, UnsupportedURLError
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.downloader import DownloaderPort
from src.domain.interfaces.notifier import NotifierPort
from src.domain.interfaces.storage import StoragePort
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.download_options import DownloadOptions
from src.shared.logging import get_logger

logger = get_logger(__name__)

DOWNLOAD_TIMEOUT_SECONDS = 600


class ProcessDownloadUseCase:
    def __init__(
        self,
        download_request_repository: DownloadRequestRepository,
        user_repository: UserRepository,
        downloader: DownloaderPort,
        storage: StoragePort,
        notifier: NotifierPort,
        max_deliverable_file_size_bytes: int,
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
        """
        self._download_request_repository = download_request_repository
        self._user_repository = user_repository
        self._downloader = downloader
        self._storage = storage
        self._notifier = notifier
        self._max_deliverable_file_size_bytes = max_deliverable_file_size_bytes

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
            timeout_seconds=DOWNLOAD_TIMEOUT_SECONDS,
        )

        try:
            file_path = await self._downloader.download(request.source_url, options)
        except (ExtractionError, UnsupportedURLError) as exc:
            logger.warning("process_download_failed", request_id=str(request_id), error=str(exc))
            request.mark_failed()
            await self._download_request_repository.update(request)
            await self._notifier.send_text(user.telegram_id, f"Не удалось скачать: {exc}")
            return

        try:
            await self._notifier.send_file(user.telegram_id, file_path)
        except NotifierError as exc:
            logger.warning(
                "process_download_delivery_failed", request_id=str(request_id), error=str(exc)
            )
            request.mark_failed()
            await self._download_request_repository.update(request)
            await self._notifier.send_text(user.telegram_id, f"Скачал, но не смог отправить: {exc}")
            return

        request.mark_done()
        await self._download_request_repository.update(request)
        logger.info("process_download_succeeded", request_id=str(request_id))
