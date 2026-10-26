"""Day 11D-1: what the worker hands the notifier (lesson 11A.1 — capture
the argument, don't trust a bare mock).

``kind`` comes from the request's spec (what was asked for); the media
facts come from the downloader's result (what the file is). A video
request's facts must reach the notifier intact, and an mp3 must never
carry the source video's dimensions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.domain.entities.download_request import DownloadRequest
from src.domain.entities.user import User
from src.domain.value_objects.deliverable_media import DeliverableMedia
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.download_spec import AudioSpec, DownloadSpec, VideoSpec, VideoTier
from src.domain.value_objects.format_kind import FormatKind
from tests.conftest import FakeErrorLocalizer
from tests.unit.test_process_download_use_case import (
    _CHAT_ID,
    _MESSAGE_ID,
    FakeDownloader,
    FakeDownloadRequestRepository,
    FakeNotifier,
    FakeUserRepository,
    _use_case,
)

_RESULT = DownloadResult(
    path=Path("/tmp/fake/v.mp4"),
    width=1080,
    height=1920,
    duration_seconds=38,
    title="A Short",
    uploader="NASA",
)


async def _deliver(spec: DownloadSpec, i18n_core: Any) -> DeliverableMedia:
    user = User.create_from_telegram(telegram_id=555)
    request = DownloadRequest.create(user_id=user.id, source_url="https://x.test/v", spec=spec)
    notifier = FakeNotifier()
    use_case = _use_case(
        FakeDownloadRequestRepository(request),
        FakeUserRepository(user),
        FakeDownloader(result=_RESULT),
        notifier,
        FakeErrorLocalizer(i18n_core),
    )
    await use_case.execute(request.id, _CHAT_ID, _MESSAGE_ID)
    (media,) = notifier.sent_media
    return media


@pytest.mark.asyncio
async def test_video_request_delivers_the_results_facts(i18n_core: Any) -> None:
    media = await _deliver(VideoSpec(VideoTier.P1080), i18n_core)
    assert media == DeliverableMedia(
        path=_RESULT.path,
        kind=FormatKind.VIDEO,
        width=1080,
        height=1920,
        duration_seconds=38,
        title="A Short",
        performer="NASA",
    )
    assert media.is_playable_video


@pytest.mark.asyncio
async def test_audio_request_is_audio_without_dimensions(i18n_core: Any) -> None:
    media = await _deliver(AudioSpec(), i18n_core)
    assert media.kind is FormatKind.AUDIO
    assert (media.width, media.height) == (None, None)
    assert media.duration_seconds == 38
    assert (media.title, media.performer) == ("A Short", "NASA")
    assert media.is_playable_audio
