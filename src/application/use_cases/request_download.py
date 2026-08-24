"""RequestDownloadUseCase — validates the URL, ensures the user exists,
persists a DownloadRequest, and enqueues the actual download job.

This is the "front door" use case, called from the Telegram handler.
The heavy lifting (yt-dlp, storage, notification) happens later, in
ProcessDownloadUseCase, run by the worker — this use case only ever
touches the database and the queue, so it returns fast even for a
video that will take minutes to download.

Day 11A: takes ``format_kind`` (video vs mp3). It defaults to
``FormatKind.VIDEO`` so /download and any other caller that doesn't care
about audio keeps working unchanged; the guided-flow preview buttons
pass AUDIO explicitly when the user taps "MP3". The value is persisted on
the request (not enqueued) — the worker reads it back from the DB.

Day 11C stage 3: takes ``quality_kind`` alongside ``format_kind``, with
the same defaulting rationale — HD_720 keeps every existing caller
(/download, and the stage-1..3 buttons) on exactly the behaviour they
had. Like ``format_kind`` it is persisted on the request rather than
enqueued: the worker rebuilds the request from the DB by id.

Day 11B: takes required, keyword-only ``chat_id``/``message_id`` — the
coordinates of the message the worker should edit with progress. No
default on purpose: unlike ``format_kind`` (which has a sane default,
VIDEO), there's no sane default "where to render progress" — a caller
that hasn't thought about it should fail loudly at the call site, not
silently enqueue a download nobody can see progress for.
"""

from __future__ import annotations

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.task_queue import TaskQueue
from src.domain.interfaces.user_repository import UserRepository
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.quality_kind import QualityKind
from src.domain.value_objects.url_validation import validate_url


class RequestDownloadUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        download_request_repository: DownloadRequestRepository,
        task_queue: TaskQueue,
    ) -> None:
        self._user_repository = user_repository
        self._download_request_repository = download_request_repository
        self._task_queue = task_queue

    async def execute(
        self,
        telegram_id: int,
        url: str,
        format_kind: FormatKind = FormatKind.VIDEO,
        quality_kind: QualityKind = QualityKind.HD_720,
        *,
        chat_id: int,
        message_id: int,
    ) -> DownloadRequest:
        validated_url = validate_url(url)

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
            format_kind=format_kind,
            quality_kind=quality_kind,
        )
        await self._download_request_repository.create(request)
        await self._task_queue.enqueue_download(request.id, chat_id, message_id)

        return request
