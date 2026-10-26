"""ProcessDownloadUseCase — progress wiring (Day 11B).

Regression-guard style, mirroring 11A.1's lesson: a fake
ProgressPublisherPort CAPTURES exactly what it was called with (not a
bare mock asserting "was called"), so a wiring bug — wrong request_id,
stale language, wrong chat/message coordinates — actually fails the test.

Day 11D-2: after the download stream the use case publishes UPLOADING
and then DONE or FAILED — on every path that tells the user anything.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import ContentUnavailableError, CorruptedRecordError, NotifierError
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.progress_phase import ProgressPhase

_MAX_BYTES = 50 * 1024 * 1024
_TIMEOUT = 1800


class _FakeRequestRepo:
    def __init__(self, request: DownloadRequest) -> None:
        self._request = request

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return self._request if request_id == self._request.id else None

    async def claim_for_processing(self, request_id: UUID) -> bool:
        return True

    async def update(self, request: DownloadRequest) -> None:
        pass


class _FakeUserRepo:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user if user_id == self._user.id else None


class _FakeStorage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path(f"/tmp/fake/{request_id}")

    async def release(self, request_id: UUID) -> None:
        return None

    async def available_bytes(self) -> int:
        return 10**12


class _FakeNotifier:
    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        pass

    async def send_text(self, telegram_id: int, text: str) -> None:
        pass


class _FakeErrorLocalizer:
    def localize(self, error_key: str, locale: str | None = None, **kwargs: object) -> str:
        return error_key


class _CapturingProgressPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int, int, str | None, DownloadProgress]] = []

    async def publish(
        self,
        request_id: UUID,
        chat_id: int,
        message_id: int,
        language: str | None,
        progress: DownloadProgress,
    ) -> None:
        self.calls.append((request_id, chat_id, message_id, language, progress))


class _ProgressEmittingDownloader:
    """Real DownloaderPort shape: actually invokes progress_callback
    during the (fake) download, exactly like YtDlpDownloader would."""

    def __init__(self, progress_events: list[DownloadProgress], result_path: Path) -> None:
        self._progress_events = progress_events
        self._result_path = result_path

    async def get_preview(self, url: str):  # pragma: no cover — not exercised here
        raise NotImplementedError

    async def download(
        self, url: str, options: DownloadOptions, progress_callback=None
    ) -> DownloadResult:
        if progress_callback is not None:
            for event in self._progress_events:
                await progress_callback(event)
        return DownloadResult(self._result_path)


@pytest.mark.asyncio
async def test_progress_events_are_published_with_correct_coordinates_and_language() -> None:
    user = User.create_from_telegram(telegram_id=555, language="ru")
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")

    events = [
        DownloadProgress(percent=10.0, downloaded_bytes=100, total_bytes=1000, speed=50.0, eta=18),
        DownloadProgress(percent=50.0, downloaded_bytes=500, total_bytes=1000, speed=60.0, eta=8),
    ]
    publisher = _CapturingProgressPublisher()
    downloader = _ProgressEmittingDownloader(events, result_path=Path("/tmp/fake/video.mp4"))

    use_case = ProcessDownloadUseCase(
        download_request_repository=_FakeRequestRepo(request),
        user_repository=_FakeUserRepo(user),
        downloader=downloader,
        storage=_FakeStorage(),
        notifier=_FakeNotifier(),
        error_localizer=_FakeErrorLocalizer(),
        progress_publisher=publisher,
        max_deliverable_file_size_bytes=_MAX_BYTES,
        download_timeout_seconds=_TIMEOUT,
        min_free_disk_bytes=0,
    )

    await use_case.execute(request.id, chat_id=777, message_id=888)

    # The download stream verbatim, then the two phase markers.
    assert [c[4] for c in publisher.calls[: len(events)]] == events
    assert [c[4].phase for c in publisher.calls[len(events) :]] == [
        ProgressPhase.UPLOADING,
        ProgressPhase.DONE,
    ]
    for req_id, chat_id, message_id, language, _ in publisher.calls:
        assert req_id == request.id
        assert chat_id == 777
        assert message_id == 888
        assert language == "ru"


@pytest.mark.asyncio
async def test_no_progress_events_means_only_the_phase_markers() -> None:
    user = User.create_from_telegram(telegram_id=1)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")
    publisher = _CapturingProgressPublisher()
    downloader = _ProgressEmittingDownloader([], result_path=Path("/tmp/fake/video.mp4"))

    use_case = ProcessDownloadUseCase(
        download_request_repository=_FakeRequestRepo(request),
        user_repository=_FakeUserRepo(user),
        downloader=downloader,
        storage=_FakeStorage(),
        notifier=_FakeNotifier(),
        error_localizer=_FakeErrorLocalizer(),
        progress_publisher=publisher,
        max_deliverable_file_size_bytes=_MAX_BYTES,
        download_timeout_seconds=_TIMEOUT,
        min_free_disk_bytes=0,
    )

    await use_case.execute(request.id, chat_id=1, message_id=2)

    assert [c[4].phase for c in publisher.calls] == [ProgressPhase.UPLOADING, ProgressPhase.DONE]


# --- Day 11D-2: final states ---------------------------------------------------------


class _Log:
    """One ordered record of what the user-facing ports saw."""

    def __init__(self) -> None:
        self.events: list[str] = []


class _OrderedPublisher(_CapturingProgressPublisher):
    def __init__(self, log: _Log, fail: bool = False) -> None:
        super().__init__()
        self._log = log
        self._fail = fail

    async def publish(
        self,
        request_id: UUID,
        chat_id: int,
        message_id: int,
        language: str | None,
        progress: DownloadProgress,
    ) -> None:
        await super().publish(request_id, chat_id, message_id, language, progress)
        self._log.events.append(f"card:{progress.phase}")
        if self._fail:
            raise ConnectionError("redis is down")


class _OrderedNotifier:
    def __init__(self, log: _Log, fail_send: bool = False) -> None:
        self._log = log
        self._fail_send = fail_send

    async def send_file(
        self, telegram_id: int, media: DeliverableMedia, caption: str | None = None
    ) -> None:
        self._log.events.append("send_file")
        if self._fail_send:
            raise NotifierError("boom")

    async def send_text(self, telegram_id: int, text: str) -> None:
        self._log.events.append(f"text:{text}")


class _RaisingDownloader(_ProgressEmittingDownloader):
    async def download(
        self, url: str, options: DownloadOptions, progress_callback=None
    ) -> DownloadResult:
        raise ContentUnavailableError("gone")


class _StatusRepo(_FakeRequestRepo):
    def __init__(self, request: DownloadRequest, log: _Log) -> None:
        super().__init__(request)
        self._log = log

    async def claim_for_processing(self, request_id: UUID) -> bool:
        self._log.events.append("status:processing")
        return True

    async def update(self, request: DownloadRequest) -> None:
        self._log.events.append(f"status:{request.status.value}")


def _use_case(
    request: DownloadRequest,
    user: User,
    log: _Log,
    *,
    downloader=None,
    notifier=None,
    publish_fails: bool = False,
) -> tuple[ProcessDownloadUseCase, _OrderedPublisher]:
    publisher = _OrderedPublisher(log, fail=publish_fails)
    use_case = ProcessDownloadUseCase(
        download_request_repository=_StatusRepo(request, log),
        user_repository=_FakeUserRepo(user),
        downloader=downloader or _ProgressEmittingDownloader([], Path("/tmp/fake/v.mp4")),
        storage=_FakeStorage(),
        notifier=notifier or _OrderedNotifier(log),
        error_localizer=_FakeErrorLocalizer(),
        progress_publisher=publisher,
        max_deliverable_file_size_bytes=_MAX_BYTES,
        download_timeout_seconds=_TIMEOUT,
        min_free_disk_bytes=0,
    )
    return use_case, publisher


def _pair() -> tuple[User, DownloadRequest]:
    user = User.create_from_telegram(telegram_id=5, language="en")
    return user, DownloadRequest.create(user_id=user.id, source_url="https://example.com/v")


@pytest.mark.asyncio
async def test_success_uploads_then_marks_done_after_the_status_is_saved() -> None:
    user, request = _pair()
    log = _Log()
    use_case, publisher = _use_case(request, user, log)

    await use_case.execute(request.id, chat_id=7, message_id=8)

    assert log.events == [
        "status:processing",
        "card:uploading",
        "send_file",
        "status:done",
        "card:done",
    ]
    assert {(c[0], c[1], c[2], c[3]) for c in publisher.calls} == {(request.id, 7, 8, "en")}


@pytest.mark.asyncio
async def test_download_failure_marks_the_card_failed_and_still_sends_the_reason() -> None:
    user, request = _pair()
    log = _Log()
    downloader = _RaisingDownloader([], Path("x"))
    use_case, _ = _use_case(request, user, log, downloader=downloader)

    await use_case.execute(request.id, chat_id=7, message_id=8)

    # Never "uploading": nothing was downloaded. The reason is its own message.
    assert log.events == [
        "status:processing",
        "status:failed",
        "card:failed",
        f"text:{ContentUnavailableError.error_key}",
    ]


@pytest.mark.asyncio
async def test_delivery_failure_marks_the_card_failed() -> None:
    user, request = _pair()
    log = _Log()
    use_case, _ = _use_case(request, user, log, notifier=_OrderedNotifier(log, fail_send=True))

    await use_case.execute(request.id, chat_id=7, message_id=8)

    assert log.events == [
        "status:processing",
        "card:uploading",
        "send_file",
        "status:failed",
        "card:failed",
        "text:error-delivery-failed",
    ]


@pytest.mark.asyncio
async def test_corrupted_record_marks_the_card_failed() -> None:
    user, request = _pair()
    log = _Log()

    class _CorruptedRepo(_StatusRepo):
        async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
            raise CorruptedRecordError(
                request_id=request.id, user_id=user.id, column="status", raw_value="?"
            )

        async def mark_failed_by_id(self, request_id: UUID) -> None:
            log.events.append("status:failed")

    use_case, publisher = _use_case(request, user, log)
    use_case._download_request_repository = _CorruptedRepo(request, log)

    await use_case.execute(request.id, chat_id=7, message_id=8)

    assert log.events[:2] == ["status:failed", "card:failed"]
    assert log.events[2].startswith("text:")
    assert publisher.calls[0][:4] == (request.id, 7, 8, "en")


@pytest.mark.asyncio
async def test_a_failing_publish_never_fails_the_delivery() -> None:
    # Pub/sub is fire-and-forget: Redis being down must cost the card,
    # not the file or the request's status.
    user, request = _pair()
    log = _Log()
    use_case, _ = _use_case(request, user, log, publish_fails=True)

    await use_case.execute(request.id, chat_id=7, message_id=8)

    assert "send_file" in log.events
    assert log.events[-2:] == ["status:done", "card:done"]
