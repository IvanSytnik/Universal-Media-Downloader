"""RequestDownloadUseCase — validates the URL, ensures the user exists,
persists a DownloadRequest, and enqueues the actual download job.

This is the "front door" use case, called from the Telegram handler.
The heavy lifting (yt-dlp, storage, notification) happens later, in
ProcessDownloadUseCase, run by the worker — this use case only ever
touches the database and the queue, so it returns fast even for a
video that will take minutes to download.

Day 11A/11C: takes the user's choice — since Day 11C (v2) a single
``spec: DownloadSpec`` instead of ``format_kind`` + ``quality_kind``.
The spec is persisted on the request (not enqueued) — the worker reads
it back from the DB by id.

Day 11C (v2): also takes the source's ``extractor_key`` — read by the
caller from the stored PreviewContext (never from callback data) — and
checks the spec against FormatPolicy BEFORE anything is persisted, so a
format switched off for that source raises ``FormatNotAllowedError``
and no request or job exists. Both ``spec`` and ``extractor_key`` are
required: a default spec would let a caller skip choosing, and a
default extractor would let it skip the policy.

Day 11B: takes required, keyword-only ``chat_id``/``message_id`` — the
coordinates of the message the worker should edit with progress. No
default on purpose: unlike the spec (which has a sane default), there's
no sane default "where to render progress" — a caller
that hasn't thought about it should fail loudly at the call site, not
silently enqueue a download nobody can see progress for.

Commit before enqueue. The request must be durable before its job
exists: a worker can start the job the instant it is enqueued, and
before this was fixed it sometimes found no row (the bot committed only
after ``execute`` returned). The repositories this use case is built
with commit per call (see ``SqlAlchemyUseCaseProvider.request_download``),
so ``create`` has committed by the time ``enqueue_download`` runs.

The flip side: a failed enqueue no longer rolls the row back. It is
marked FAILED right away and ``DownloadEnqueueError`` raised (the queue's
own exception chained), which the handlers turn into ``error-internal``. Left PENDING, it would
sit until the stale-request reaper "rescued" it 40 minutes later, with
a message about a request the user was already told had failed.
"""

from __future__ import annotations

from src.application.policies.format_policy import FormatPolicy
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import DownloadEnqueueError, FormatNotAllowedError
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.task_queue import TaskQueue
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.download_spec import DownloadSpec
from src.domain.value_objects.url_validation import validate_url
from src.shared.logging import bind_log_context, get_logger

logger = get_logger(__name__)


class RequestDownloadUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        download_request_repository: DownloadRequestRepository,
        task_queue: TaskQueue,
        format_policy: FormatPolicy,
    ) -> None:
        self._user_repository = user_repository
        self._download_request_repository = download_request_repository
        self._task_queue = task_queue
        self._format_policy = format_policy

    async def execute(
        self,
        telegram_id: int,
        url: str,
        spec: DownloadSpec,
        extractor_key: str,
        *,
        chat_id: int,
        message_id: int,
    ) -> DownloadRequest:
        validated_url = validate_url(url)
        if not self._format_policy.is_allowed(extractor_key, spec):
            raise FormatNotAllowedError

        user = await self._user_repository.get_by_telegram_id(telegram_id)
        if user is None:
            # Defensive: in practice /start already registers the user.
            # Not erroring here means /download works even if a user
            # somehow reaches it without /start (e.g. bot restart edge
            # cases) — registering on the fly is cheap and correct.
            user = await self._user_repository.create(User.create_from_telegram(telegram_id))

        request = DownloadRequest.create(
            user_id=user.id,
            source_url=validated_url,
            spec=spec,
        )
        # The rest of this update's log lines and Sentry events carry
        # both (ADR 0006).
        bind_log_context(request_id=str(request.id), extractor_key=extractor_key)
        await self._download_request_repository.create(request)
        try:
            await self._task_queue.enqueue_download(request.id, chat_id, message_id)
        except Exception as exc:
            logger.error(
                "request_download_enqueue_failed",
                request_id=str(request.id),
                error=f"{type(exc).__name__}: {exc}",
            )
            await self._download_request_repository.mark_failed_by_id(request.id)
            raise DownloadEnqueueError from exc

        return request
