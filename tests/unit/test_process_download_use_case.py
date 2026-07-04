"""ProcessDownloadUseCase tests using in-memory fakes — no DB, no yt-dlp,
no Telegram. Covers the three outcomes: success, download failure,
delivery failure.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from src.application.use_cases.process_download import ProcessDownloadUseCase
from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.exceptions import ExtractionError, NotifierError
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.enums import DownloadStatus


class FakeDownloadRequestRepository:
    def __init__(self, request: DownloadRequest) -> None:
        self._request = request
        self.updates: list[DownloadStatus] = []

    async def get_by_id(self, request_id: UUID) -> DownloadRequest | None:
        return self._request if request_id == self._request.id else None

    async def create(self, download_request: DownloadRequest) -> DownloadRequest:
        raise NotImplementedError

    async def update(self, download_request: DownloadRequest) -> None:
        self.updates.append(download_request.status)

    async def list_by_user(self, user_id: UUID, limit: int = 20) -> list[DownloadRequest]:
        raise NotImplementedError


class FakeUserRepository:
    def __init__(self, user: User) -> None:
        self._user = user

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._user if user_id == self._user.id else None

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        raise NotImplementedError

    async def create(self, user: User) -> User:
        raise NotImplementedError


class FakeDownloader:
    def __init__(self, result_path: Path | None = None, error: Exception | None = None) -> None:
        self._result_path = result_path
        self._error = error

    async def get_preview(self, url: str):  # noqa: ANN201 — not exercised in these tests
        raise NotImplementedError

    async def download(self, url: str, options: DownloadOptions) -> Path:
        if self._error is not None:
            raise self._error
        assert self._result_path is not None
        return self._result_path


class FakeStorage:
    def temp_dir_for_request(self, request_id: UUID) -> Path:
        return Path(f"/tmp/fake/{request_id}")

    async def cleanup_expired(self, max_age_seconds: int) -> int:
        return 0


class FakeNotifier:
    def __init__(self, fail_send_file: bool = False) -> None:
        self.fail_send_file = fail_send_file
        self.sent_files: list[tuple[int, Path]] = []
        self.sent_texts: list[tuple[int, str]] = []

    async def send_file(
        self, telegram_id: int, file_path: Path, caption: str | None = None
    ) -> None:
        if self.fail_send_file:
            raise NotifierError("file too large")
        self.sent_files.append((telegram_id, file_path))

    async def send_text(self, telegram_id: int, text: str) -> None:
        self.sent_texts.append((telegram_id, text))


def _make_request_and_user() -> tuple[DownloadRequest, User]:
    user = User.create_from_telegram(telegram_id=555)
    request = DownloadRequest.create(user_id=user.id, source_url="https://example.com/video")
    return request, user


@pytest.mark.asyncio
async def test_successful_download_marks_done_and_sends_file() -> None:
    request, user = _make_request_and_user()
    result_path = Path("/tmp/fake/video.mp4")

    request_repo = FakeDownloadRequestRepository(request)
    user_repo = FakeUserRepository(user)
    downloader = FakeDownloader(result_path=result_path)
    notifier = FakeNotifier()

    use_case = ProcessDownloadUseCase(
        request_repo, user_repo, downloader, FakeStorage(), notifier,
        max_deliverable_file_size_bytes=50 * 1024 * 1024,
    )
    await use_case.execute(request.id)

    assert request.status == DownloadStatus.DONE
    assert request_repo.updates == [DownloadStatus.PROCESSING, DownloadStatus.DONE]
    assert notifier.sent_files == [(555, result_path)]


@pytest.mark.asyncio
async def test_download_failure_marks_failed_and_notifies_text() -> None:
    request, user = _make_request_and_user()

    request_repo = FakeDownloadRequestRepository(request)
    user_repo = FakeUserRepository(user)
    downloader = FakeDownloader(error=ExtractionError("video unavailable"))
    notifier = FakeNotifier()

    use_case = ProcessDownloadUseCase(
        request_repo, user_repo, downloader, FakeStorage(), notifier,
        max_deliverable_file_size_bytes=50 * 1024 * 1024,
    )
    await use_case.execute(request.id)

    assert request.status == DownloadStatus.FAILED
    assert request_repo.updates == [DownloadStatus.PROCESSING, DownloadStatus.FAILED]
    assert notifier.sent_files == []
    assert len(notifier.sent_texts) == 1
    assert notifier.sent_texts[0][0] == 555


@pytest.mark.asyncio
async def test_delivery_failure_marks_failed_and_notifies_text() -> None:
    request, user = _make_request_and_user()
    result_path = Path("/tmp/fake/video.mp4")

    request_repo = FakeDownloadRequestRepository(request)
    user_repo = FakeUserRepository(user)
    downloader = FakeDownloader(result_path=result_path)
    notifier = FakeNotifier(fail_send_file=True)

    use_case = ProcessDownloadUseCase(
        request_repo, user_repo, downloader, FakeStorage(), notifier,
        max_deliverable_file_size_bytes=50 * 1024 * 1024,
    )
    await use_case.execute(request.id)

    assert request.status == DownloadStatus.FAILED
    assert len(notifier.sent_texts) == 1


@pytest.mark.asyncio
async def test_unknown_request_id_is_a_noop() -> None:
    request, user = _make_request_and_user()
    request_repo = FakeDownloadRequestRepository(request)
    user_repo = FakeUserRepository(user)
    notifier = FakeNotifier()

    use_case = ProcessDownloadUseCase(
        request_repo,
        user_repo,
        FakeDownloader(),
        FakeStorage(),
        notifier,
        max_deliverable_file_size_bytes=50 * 1024 * 1024,
    )

    from uuid import uuid4

    await use_case.execute(uuid4())

    assert request_repo.updates == []
    assert notifier.sent_files == []
    assert notifier.sent_texts == []
