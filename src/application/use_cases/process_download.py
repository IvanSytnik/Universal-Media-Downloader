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

Day 11A.1 — HOTFIX. The requested ``format_kind`` (video/mp3) is now
threaded from the persisted request into ``DownloadOptions``. It was
persisted correctly in 11A but this last read-side link was missing, so
``DownloadOptions`` always used its ``VIDEO`` default and the worker
downloaded video even when the user tapped MP3. This is the ONE line
that closes the loop between "what the user asked for" (in the DB) and
"what yt-dlp actually fetches".

Day 11B — real-time progress. ``execute`` now takes ``chat_id`` and
``message_id`` (the coordinates of the message to edit with progress —
a transport detail, threaded through the job payload, never persisted;
contrast with ``format_kind`` above). It builds a ``progress_callback``
closing over the already-loaded ``request``/``user`` and hands it to
``downloader.download(...)``; the callback's only job is to forward each
``DownloadProgress`` to ``ProgressPublisherPort.publish`` with the
routing/locale extras attached. No new DB reads on the progress path.

Day 11C.3 — the load itself can now fail *reportably*. Reading a row
whose stored status is unreadable raises ``CorruptedRecordError`` from
``get_by_id``, i.e. before ``request`` exists — so the normal failure
path (mark the entity failed, notify) is unavailable: there is no
entity. That case gets its own recovery below, which leans on the two
uuid columns the exception carries out of the failed read. Without it
the error would escape the job unhandled and the user, whose request
was already accepted, would simply never hear back (bugs #6 and #13).

Day 11D-2 — the progress card gets a final state. ``UPLOADING`` is
published before the file goes to Telegram, then ``DONE`` or ``FAILED``
once the request's status is saved — through the same
``ProgressPublisherPort``. Pub/sub is fire-and-forget, so the card only
says "sent" / "failed"; the failure reason still goes out as its own
message via the notifier, the reliable path. A publish that fails is
logged and ignored: the card is cosmetic, the delivery is not.

Stale-request reaper (ADR 0004) — the start is a CLAIM, not a write.
``claim_for_processing`` moves the request to PROCESSING only if it is
still active; a request the reaper already failed (or a duplicate job
for a finished one) is skipped without downloading or messaging
anything — the user has already been told. An arq retry after a worker
crash finds it PROCESSING and re-claims it, as before.

Disk guard (ADR 0005). Once claimed, the request's temp directory is
released in a ``finally`` — delivered, failed or refused, the file does
not outlive the job (it used to wait for the cron's TTL). Before
downloading, free space is checked against ``min_free_disk_bytes``; below
it the request fails with ``InsufficientStorageError`` without starting
yt-dlp.
"""

from __future__ import annotations

from uuid import UUID

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import (
    CorruptedRecordError,
    DownloaderError,
    ExtractionError,
    FileTooLargeError,
    InsufficientStorageError,
    NotifierError,
    UnsupportedURLError,
)
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.downloader import DownloaderPort
from src.domain.interfaces.error_localizer import ErrorLocalizerPort
from src.domain.interfaces.notifier import NotifierPort
from src.domain.interfaces.progress_publisher import ProgressPublisherPort
from src.domain.interfaces.storage import StoragePort
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_progress import DownloadProgress, phase_marker
from src.domain.value_objects.download_spec import spec_kind
from src.domain.value_objects.progress_phase import ProgressPhase
from src.shared.logging import describe_error, get_logger

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
        progress_publisher: ProgressPublisherPort,
        max_deliverable_file_size_bytes: int,
        download_timeout_seconds: int,
        min_free_disk_bytes: int,
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

        `progress_publisher` (Day 11B) broadcasts progress snapshots
        during the download; see the module docstring.

        `min_free_disk_bytes` (disk guard) is the free-space floor below
        which a download is refused; 0 disables the check.
        """
        self._download_request_repository = download_request_repository
        self._user_repository = user_repository
        self._downloader = downloader
        self._storage = storage
        self._notifier = notifier
        self._error_localizer = error_localizer
        self._progress_publisher = progress_publisher
        self._max_deliverable_file_size_bytes = max_deliverable_file_size_bytes
        self._download_timeout_seconds = download_timeout_seconds
        self._min_free_disk_bytes = min_free_disk_bytes

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

    async def _publish_phase(
        self,
        request_id: UUID,
        chat_id: int,
        message_id: int,
        language: str | None,
        phase: ProgressPhase,
    ) -> None:
        """Move the progress card to ``phase``; never fails the job."""
        try:
            await self._progress_publisher.publish(
                request_id, chat_id, message_id, language, phase_marker(phase)
            )
        except Exception as exc:  # noqa: BLE001 — the card is cosmetic, see module docstring
            logger.warning(
                "process_download_phase_publish_failed",
                request_id=str(request_id),
                phase=phase,
                error=describe_error(exc),
            )

    async def _report_corrupted_record(
        self, exc: CorruptedRecordError, chat_id: int, message_id: int
    ) -> None:
        """Recovery for a row that couldn't be read into an entity.

        Marks the request failed by id (``update`` needs the entity we
        failed to build) and sends one short localized message. The user
        is reachable because the exception carries ``user_id`` from the
        same row — the uuid columns survive an unreadable enum column
        next to them.

        Full diagnostics (which column, what the raw value was) go to
        the log and never into the message: the user can't act on them,
        and leaking them is bug #6.
        """
        logger.error(
            "process_download_corrupted_record",
            request_id=str(exc.request_id),
            user_id=str(exc.user_id),
            column=exc.column,
            raw_value=exc.raw_value,
        )
        await self._download_request_repository.mark_failed_by_id(exc.request_id)

        user = await self._user_repository.get_by_id(exc.user_id)
        if user is None or user.telegram_id is None:
            return
        await self._publish_phase(
            exc.request_id, chat_id, message_id, user.language, ProgressPhase.FAILED
        )
        await self._notifier.send_text(
            user.telegram_id,
            self._error_localizer.localize(exc.error_key, user.language),
        )

    async def execute(self, request_id: UUID, chat_id: int, message_id: int) -> None:
        try:
            request = await self._download_request_repository.get_by_id(request_id)
        except CorruptedRecordError as exc:
            await self._report_corrupted_record(exc, chat_id, message_id)
            return

        if request is None:
            logger.warning("process_download_request_not_found", request_id=str(request_id))
            return

        user = await self._user_repository.get_by_id(request.user_id)
        if user is None or user.telegram_id is None:
            logger.warning("process_download_user_not_found", request_id=str(request_id))
            return

        if not await self._download_request_repository.claim_for_processing(request.id):
            logger.warning(
                "process_download_skipped_inactive",
                request_id=str(request_id),
                status=request.status,
            )
            return
        request.mark_processing()

        try:
            await self._process(request, user, user.telegram_id, chat_id, message_id)
        finally:
            await self._storage.release(request.id)

    async def _fail(
        self,
        request: DownloadRequest,
        user: User,
        telegram_id: int,
        chat_id: int,
        message_id: int,
        text: str,
    ) -> None:
        """Mark failed, move the card to FAILED, tell the user ``text``."""
        request.mark_failed()
        await self._download_request_repository.update(request)
        await self._publish_phase(
            request.id, chat_id, message_id, user.language, ProgressPhase.FAILED
        )
        await self._notifier.send_text(telegram_id, text)

    async def _process(
        self,
        request: DownloadRequest,
        user: User,
        telegram_id: int,
        chat_id: int,
        message_id: int,
    ) -> None:
        request_id = request.id
        if self._min_free_disk_bytes:
            available = await self._storage.available_bytes()
            if available < self._min_free_disk_bytes:
                logger.warning(
                    "process_download_rejected_low_disk",
                    request_id=str(request_id),
                    available_bytes=available,
                    min_free_bytes=self._min_free_disk_bytes,
                    error_key=InsufficientStorageError.error_key,
                )
                await self._fail(
                    request,
                    user,
                    telegram_id,
                    chat_id,
                    message_id,
                    self._localize_failure(InsufficientStorageError(), user.language),
                )
                return

        output_dir = self._storage.temp_dir_for_request(request.id)
        options = DownloadOptions(
            output_dir=output_dir,
            max_filesize_bytes=self._max_deliverable_file_size_bytes,
            timeout_seconds=self._download_timeout_seconds,
            # Day 11A.1 / 11C: carry the user's choice through to yt-dlp.
            # Without this the DownloadOptions default wins — the MP3
            # button silently delivers video, 1080p silently downloads
            # 720p. Guarded by an argument-capture test, not a bare
            # downloader mock.
            spec=request.spec,
        )

        async def _on_progress(progress: DownloadProgress) -> None:
            # Closes over the already-loaded request/user — no extra DB
            # read per progress event (request.id is stable; user.language
            # was already fetched above for the failure path too).
            await self._progress_publisher.publish(
                request.id, chat_id, message_id, user.language, progress
            )

        try:
            result = await self._downloader.download(
                request.source_url, options, progress_callback=_on_progress
            )
        except (ExtractionError, UnsupportedURLError) as exc:
            logger.warning(
                "process_download_failed",
                request_id=str(request_id),
                error_key=getattr(exc, "error_key", None),
                error=describe_error(exc),
            )
            await self._fail(
                request,
                user,
                telegram_id,
                chat_id,
                message_id,
                self._localize_failure(exc, user.language),
            )
            return

        await self._publish_phase(
            request.id, chat_id, message_id, user.language, ProgressPhase.UPLOADING
        )

        try:
            # Day 11D-1: the notifier picks video / audio / document from
            # this; `kind` is what was asked for, the facts what the file is.
            media = DeliverableMedia.from_result(result, spec_kind(request.spec))
            await self._notifier.send_file(telegram_id, media)
        except NotifierError as exc:
            logger.warning(
                "process_download_delivery_failed",
                request_id=str(request_id),
                error=describe_error(exc),
            )
            await self._fail(
                request,
                user,
                telegram_id,
                chat_id,
                message_id,
                self._error_localizer.localize("error-delivery-failed", user.language),
            )
            return

        request.mark_done()
        await self._download_request_repository.update(request)
        await self._publish_phase(
            request.id, chat_id, message_id, user.language, ProgressPhase.DONE
        )
        logger.info("process_download_succeeded", request_id=str(request_id))
