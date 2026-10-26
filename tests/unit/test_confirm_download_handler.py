"""Day 11C (v2): the ``dl:`` handler — the only tap that creates a request.

Pinned here: it CLAIMS the token (``pop`` → Redis GETDEL) and never reads
it non-destructively, so a double tap enqueues once; the spec comes from
the payload but the extractor from the stored context; and a payload the
policy refuses is answered with ``error-format-not-allowed``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.application.policies.format_policy import FormatPolicy
from src.domain.value_objects.download_spec import (
    DEFAULT_DOWNLOAD_SPEC,
    AudioSpec,
    VideoSpec,
    VideoTier,
)
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.preview_context import PreviewContext
from src.presentation.telegram.handlers.download_flow import handle_confirm_download
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core
from tests.conftest import FakeI18n
from tests.unit.handler_fakes import (
    AllowAll,
    Callback,
    Provider,
    RecordingStore,
    make_message,
    settings,
)

TOKEN = "c" * 32
_CTX = PreviewContext(
    url="https://www.youtube.com/watch?v=x", extractor_key="youtube", max_compatible_short_side=1080
)


@pytest.fixture
async def i18n() -> Any:
    core = create_i18n_core()
    await core.startup()
    return FakeI18n(core, DEFAULT_LOCALE)


async def _tap(
    data: str, store: RecordingStore, provider: Provider, i18n: Any
) -> tuple[Callback, Any]:
    message = make_message("preview text", message_id=5)
    callback = Callback(data, message)
    await handle_confirm_download(
        callback,  # type: ignore[arg-type]
        i18n,
        provider,  # type: ignore[arg-type]
        store,  # type: ignore[arg-type]
        settings(),
        AllowAll(),
    )
    return callback, message


async def test_dl_claims_the_token_and_never_reads_it_non_destructively(i18n: Any) -> None:
    store = RecordingStore({TOKEN: _CTX})
    provider = Provider(FormatPolicy({}))

    await _tap(f"dl:{TOKEN}:v1080", store, provider, i18n)

    # pop is the store's GETDEL (test_preview_context_store pins that);
    # a get-then-delete here would reopen the double-tap race.
    assert store.calls == ["pop"]
    assert [r.spec for r in provider.created] == [VideoSpec(VideoTier.P1080)]


async def test_double_tap_enqueues_once(i18n: Any) -> None:
    store = RecordingStore({TOKEN: _CTX})
    provider = Provider(FormatPolicy({}))

    await _tap(f"dl:{TOKEN}:v720", store, provider, i18n)
    second, _ = await _tap(f"dl:{TOKEN}:v720", store, provider, i18n)

    assert len(provider.queue.enqueued_download_ids) == 1
    assert second.answers == [(i18n.get("flow-preview-stale"), True)]


@pytest.mark.parametrize(
    ("code", "spec"),
    [
        ("", DEFAULT_DOWNLOAD_SPEC),  # legacy bare dl:<token>
        (":v", DEFAULT_DOWNLOAD_SPEC),  # Day 11A tierless video
        (":v720", VideoSpec(VideoTier.P720)),
        (":v1080", VideoSpec(VideoTier.P1080)),
        (":vbest", VideoSpec(VideoTier.BEST)),
        (":a", AudioSpec()),
        (":zzz", DEFAULT_DOWNLOAD_SPEC),  # unknown → default, no crash
    ],
)
async def test_payload_spec_is_what_gets_persisted(i18n: Any, code: str, spec: Any) -> None:
    store = RecordingStore({TOKEN: _CTX})
    provider = Provider(FormatPolicy({}))

    await _tap(f"dl:{TOKEN}{code}", store, provider, i18n)

    assert [r.spec for r in provider.created] == [spec]


async def test_stale_mp3_button_after_kill_switch_is_refused(i18n: Any) -> None:
    """The card was rendered with MP3; then DISABLED_FORMATS gained
    {"youtube": ["audio"]} and the bot restarted. The extractor is the
    STORED one — the payload has no say in it."""
    store = RecordingStore({TOKEN: _CTX})
    provider = Provider(FormatPolicy({"youtube": [FormatKind.AUDIO]}))

    callback, message = await _tap(f"dl:{TOKEN}:a", store, provider, i18n)

    assert callback.answers == [(i18n.get("error-format-not-allowed"), True)]
    assert provider.created == []
    assert provider.queue.enqueued_download_ids == []
    # The card is left as it was (no "download started").
    assert message.edits == []
    # The token is spent: a refused card should not stay live.
    assert await store.get(TOKEN) is None


async def test_video_still_allowed_when_only_audio_is_disabled(i18n: Any) -> None:
    store = RecordingStore({TOKEN: _CTX})
    provider = Provider(FormatPolicy({"youtube": [FormatKind.AUDIO]}))

    await _tap(f"dl:{TOKEN}:v720", store, provider, i18n)

    assert [r.spec for r in provider.created] == [VideoSpec(VideoTier.P720)]
