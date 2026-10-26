"""ReapStaleRequestsUseCase — fail requests no live job is working on.

Runs on the worker's cron (ADR 0004). A request is stale when it is
still PENDING/PROCESSING but its last update is older than any live job
could be: arq cancels a job at ``job_timeout``, so past
``job_timeout + grace`` nothing is coming back for it. That covers a
worker crash or redeploy mid-job, arq's own cancel at ``job_timeout``
(the coroutine is cancelled before it can mark anything), and a queue
message that was lost or never consumed.

Order matters for idempotency: the FAILED transition is committed by the
repository first (``fail_stale`` is a compare-and-set, so one row is
reaped once, however many reapers run), and only the rows it actually
moved are notified. A crash between the two loses a notification; it
never sends two. A failing notification is logged and does not stop the
rest of the batch.

The progress card is NOT moved to FAILED: its chat/message coordinates
ride only in the job payload (Day 11B) and are not persisted, so the
reaper cannot address it. The text message is the reliable channel.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from src.domain.exceptions import StaleRequestError
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.error_localizer import ErrorLocalizerPort
from src.domain.interfaces.notifier import NotifierPort
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.stale_request import StaleRequest
from src.shared.logging import describe_error, get_logger

logger = get_logger(__name__)


class ReapStaleRequestsUseCase:
    def __init__(
        self,
        download_request_repository: DownloadRequestRepository,
        user_repository: UserRepository,
        notifier: NotifierPort,
        error_localizer: ErrorLocalizerPort,
        *,
        stale_after: timedelta,
        batch_size: int,
        clock: Callable[[], datetime],
    ) -> None:
        self._download_request_repository = download_request_repository
        self._user_repository = user_repository
        self._notifier = notifier
        self._error_localizer = error_localizer
        self._stale_after = stale_after
        self._batch_size = batch_size
        self._clock = clock

    async def execute(self) -> list[StaleRequest]:
        """One batch per call; whatever is left goes on the next tick."""
        reaped = await self._download_request_repository.fail_stale(
            self._clock() - self._stale_after, self._batch_size
        )
        for stale in reaped:
            logger.warning(
                "stale_request_reaped",
                request_id=str(stale.request_id),
                user_id=str(stale.user_id),
                previous_status=stale.previous_status,
                error_key=StaleRequestError.error_key,
            )
            await self._notify(stale)
        return reaped

    async def _notify(self, stale: StaleRequest) -> None:
        try:
            user = await self._user_repository.get_by_id(stale.user_id)
            if user is None or user.telegram_id is None:
                logger.warning("stale_request_user_unreachable", request_id=str(stale.request_id))
                return
            await self._notifier.send_text(
                user.telegram_id,
                self._error_localizer.localize(StaleRequestError.error_key, user.language),
            )
        except Exception as exc:  # noqa: BLE001 — one unreachable user must not stop the batch
            logger.warning(
                "stale_request_notify_failed",
                request_id=str(stale.request_id),
                error=describe_error(exc),
            )
