"""RequestDownloadUseCase — validates the URL, ensures the user exists,
persists a DownloadRequest, and enqueues the actual download job.

This is the "front door" use case, called from the Telegram handler.
The heavy lifting (yt-dlp, storage, notification) happens later, in
ProcessDownloadUseCase, run by the worker — this use case only ever
touches the database and the queue, so it returns fast even for a
video that will take minutes to download.
"""

from __future__ import annotations

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.interfaces.download_request_repository import DownloadRequestRepository
from src.domain.interfaces.task_queue import TaskQueue
from src.domain.interfaces.user_repository import UserRepository
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

    async def execute(self, telegram_id: int, url: str) -> DownloadRequest:
        validated_url = validate_url(url)

        user = await self._user_repository.get_by_telegram_id(telegram_id)
        if user is None:
            # Defensive: in practice /start already registers the user.
            # Not erroring here means /download works even if a user
            # somehow reaches it without /start (e.g. bot restart edge
            # cases) — registering on the fly is cheap and correct.
            user = await self._user_repository.create(User.create_from_telegram(telegram_id))

        request = DownloadRequest.create(user_id=user.id, source_url=validated_url)
        await self._download_request_repository.create(request)
        await self._task_queue.enqueue_download(request.id)

        return request
