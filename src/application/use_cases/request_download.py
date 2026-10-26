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
"""

from __future__ import annotations

from src.application.policies.format_policy import FormatPolicy
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import FormatNotAllowedError
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.task_queue import TaskQueue
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.download_spec import DownloadSpec
from src.domain.value_objects.url_validation import validate_url
from src.shared.logging import bind_log_context


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
        await self._task_queue.enqueue_download(request.id, chat_id, message_id)

        return request
