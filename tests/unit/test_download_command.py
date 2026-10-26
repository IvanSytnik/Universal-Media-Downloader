"""Day 11C (v2): ``/download <url>`` — no buttons, so the policy picks the
spec (``default_video_spec``) and refuses a disabled video exactly like
the button path; the allowlist (and blocked_domains) runs before the
preview reaches yt-dlp — on this path and on the guided one.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.application.policies.format_policy import DIRECT_VIDEO_SPEC, FormatPolicy
from src.domain.value_objects.download_spec import DownloadSpec, VideoSpec, VideoTier
from src.domain.value_objects.format_kind import FormatKind
from src.presentation.telegram.handlers.download import handle_download
from src.presentation.telegram.handlers.download_flow import handle_plain_url
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core
from tests.conftest import FakeI18n
from tests.unit.handler_fakes import (
    AllowAll,
    DownQueue,
    Provider,
    RecordingStore,
    make_message,
    preview,
    settings,
)

URL = "https://www.youtube.com/watch?v=x"


@pytest.fixture
async def i18n() -> Any:
    core = create_i18n_core()
    await core.startup()
    return FakeI18n(core, DEFAULT_LOCALE)


async def _run(text: str, provider: Provider, policy: FormatPolicy, i18n: Any) -> Any:
    message = make_message(text)
    await handle_download(
        message,
        i18n,
        provider,  # type: ignore[arg-type]
        settings(),
        AllowAll(),
        policy,
    )
    return message


@pytest.mark.parametrize(
    ("short_side", "spec"),
    [
        (1080, VideoSpec(VideoTier.P720)),  # quality step exists → 720p
        (720, DIRECT_VIDEO_SPEC),  # TikTok-like → best, like the button
        (None, DIRECT_VIDEO_SPEC),
    ],
)
async def test_spec_comes_from_the_policy(
    i18n: Any, short_side: int | None, spec: DownloadSpec
) -> None:
    policy = FormatPolicy({})
    provider = Provider(policy, preview("youtube", short_side))

    await _run(f"/download {URL}", provider, policy, i18n)

    assert [r.spec for r in provider.created] == [spec]


async def test_disabled_video_is_refused_like_the_button(i18n: Any) -> None:
    policy = FormatPolicy({"youtube": [FormatKind.VIDEO]})
    provider = Provider(policy, preview("youtube", 1080))

    message = await _run(f"/download {URL}", provider, policy, i18n)

    assert provider.created == []
    assert provider.queue.enqueued_download_ids == []
    (status,) = message.sent
    assert status.edits == [i18n.get("error-format-not-allowed")]


async def test_site_outside_the_allowlist_never_reaches_the_preview(i18n: Any) -> None:
    policy = FormatPolicy({})
    provider = Provider(policy)

    message = await _run("/download https://example.org/video", provider, policy, i18n)

    assert provider.preview_use_case.urls == []
    assert provider.created == []
    # Refused before even the "download started" status message.
    (reply,) = message.sent
    prefix = i18n.get("error-bad-url", reason="")
    assert reply.text is not None and reply.text.startswith(prefix)
    assert "youtube.com" in reply.text  # the validator's list of supported sites


@pytest.mark.parametrize(
    "url", ["https://music.youtube.com/watch?v=x", "https://example.org/video"]
)
async def test_guided_flow_refuses_blocked_and_unlisted_sites_before_the_preview(
    i18n: Any, url: str
) -> None:
    # Same gate on the other entry point (a pasted link).
    policy = FormatPolicy({})
    provider = Provider(policy)
    store = RecordingStore()
    message = make_message(url)

    await handle_plain_url(
        message,
        i18n,
        settings(),
        store,  # type: ignore[arg-type]
        AllowAll(),
        provider,  # type: ignore[arg-type]
        policy,
    )

    assert provider.preview_use_case.urls == []
    assert store.calls == []
    (reply,) = message.sent
    assert reply.text is not None and reply.text.startswith(i18n.get("error-bad-url", reason=""))


async def test_youtube_music_is_refused_before_the_preview(i18n: Any) -> None:
    policy = FormatPolicy({})
    provider = Provider(policy)

    message = await _run("/download https://music.youtube.com/watch?v=x", provider, policy, i18n)

    assert provider.preview_use_case.urls == []
    assert provider.created == []
    (reply,) = message.sent
    assert reply.text is not None and reply.text.startswith(i18n.get("error-bad-url", reason=""))


async def test_unreachable_queue_turns_the_status_message_into_an_error(i18n: Any) -> None:
    policy = FormatPolicy({})
    provider = Provider(policy, preview("youtube", 1080), queue=DownQueue())

    message = await _run(f"/download {URL}", provider, policy, i18n)

    (status,) = message.sent
    assert status.text == i18n.get("download-started")
    # No longer claims the download started; no raw Redis text either.
    assert status.edits == [i18n.get("error-internal")]
    assert "redis" not in status.edits[0].lower()
    [request] = provider.created
    assert provider.requests.failed_ids == [request.id]
