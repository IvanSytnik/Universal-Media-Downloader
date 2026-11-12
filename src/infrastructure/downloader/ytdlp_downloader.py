"""yt-dlp implementation of DownloaderPort.

Uses yt-dlp's native Python API (`yt_dlp.YoutubeDL`), not a CLI subprocess
wrapper (docs/architecture.md, Process isolation).

**Why `download()` spawns a fresh process per call (Day 5):**

`get_preview()` (Day 4) ran `extract_info` in the default thread pool —
fine for a quick metadata lookup, until it isn't (see "Preview timeout"
below: it now runs in a child process too). Real downloads are
long-running and must be cancellable with a hard guarantee: if a download hangs (dead
peer, yt-dlp bug, huge playlist misdetected as single video), the worker
must be able to kill it, not wait forever.

A shared `concurrent.futures.ProcessPoolExecutor` does NOT give this
guarantee: `Future.cancel()` only works on tasks that haven't started
yet; once a pool worker is executing, there is no public stdlib API to
kill just that one task without shutting down the whole pool. So instead,
`download()` spawns a brand new `multiprocessing.Process` for every
call and calls `process.terminate()` if it doesn't finish within
`options.timeout_seconds`. This costs process-startup overhead (tens of
milliseconds) per download, which is negligible next to typical download
times (seconds to minutes) — a reasonable trade for a real kill switch.

**Day 10 — error categorization.** Both the preview path and the download
path used to collapse every yt-dlp failure into a single generic
``ExtractionError``. They now run the raw yt-dlp message through
``classify_error`` (see error_classifier.py) and raise the specific
domain category (private / geo / age / unavailable / unsupported-media /
generic fallback). The raw message stays in the LOG only — the raised
exception carries a semantic ``error_key``, never the diagnostic text
(bug #6). The Presentation layer and the worker path both map that key
to a localized message.

**Day 11A — audio vs video.** ``download()`` honours the requested
kind (since Day 11C v2: ``options.spec``). VIDEO downloads an mp4 (see Day 11C below for
the current selector). AUDIO uses a bestaudio selector
plus an ``FFmpegExtractAudio`` postprocessor that produces an mp3 — the
system ffmpeg binary (installed in bot.Dockerfile) does the
transcode. The final filename still comes from ``post_hooks`` (bug #4):
the postprocessor changes the extension to .mp3, and post_hooks reports
the real post-transcode path, so no prediction is needed.

**Day 11B — real-time progress.** ``download()`` accepts an optional
``progress_callback`` (async, domain-shaped: takes a ``DownloadProgress``
— see ``DownloaderPort``). yt-dlp's own ``progress_hooks`` run *inside
the child process*, synchronously, on its own thread of control — they
cannot themselves ``await`` anything. Bridging that to an async callback
on the event loop needs two hops, each using the narrowest thread-safe
primitive for its boundary:

1. Child → executor thread: the child's progress hook puts a small raw
   dict onto a second ``multiprocessing.Queue`` (``progress_queue``,
   alongside the existing ``result_queue``). ``_wait_and_drain_progress``
   (still running inside ``run_in_executor``, exactly where
   ``process.join(timeout)`` used to block alone) now polls that queue
   with a short timeout instead of one long blocking join — this is what
   lets progress out *during* the download without changing the
   timeout/terminate contract at all (see its docstring).
2. Executor thread → event loop: each drained item is handed to a plain
   **synchronous** ``progress_sink`` callback (internal to this module,
   never crosses the ``DownloaderPort`` boundary). ``download()`` builds
   ``progress_sink`` as a closure that does exactly one thing —
   ``loop.call_soon_threadsafe(bridge.put_nowait, raw)`` — the only
   sanctioned way to touch an ``asyncio.Queue`` from another thread. A
   dedicated asyncio task then drains ``bridge`` natively on the event
   loop and ``await``s the real (domain-facing) ``progress_callback`` for
   each item — zero blocking of the event loop at any point, and the
   drain-task side is fully testable without real threads or processes.

Progress hooks fire during the download phase; yt-dlp's own detailed
postprocessing progress (ffmpeg mp3 transcode percentage) is still out
of scope — but the download→postprocess BOUNDARY itself
is now surfaced (Day 11B.1). yt-dlp's ``status == "finished"`` event
already marks that exact boundary; it used to be discarded outright (see
_download_worker_entrypoint's docstring history). AUDIO downloads now
forward it as a single ``DownloadProgress(phase=ProgressPhase.CONVERTING)``
snapshot through the same queue/bridge/callback path as every other
progress event — no second channel. VIDEO downloads never emit it: there
is no user-visible "converting" step on that path.

**Day 11C stage 1 — real quality instead of 360p.** Two independent
causes made every video download come back as ``format 18`` (360p),
diagnosed live in docker:

1. The pinned yt-dlp (2026.07.04) predated YouTube's SABR rollout, so
   the high formats it did list 403'd on download and only the single
   combined 360p format worked. yt-dlp 2026.08.19 picks a working client
   on its own (visionos at the time of writing) and fetches 1080p avc1.
   Hence the hard version floor in pyproject.toml — this is a *runtime
   correctness* pin, not a routine upgrade.
2. Our own ``player_client=["android", "web"]`` override, originally a
   403 mitigation, had itself become the cause: it pinned yt-dlp to
   clients YouTube no longer serves full formats to. It is GONE from
   both the download opts and ``_YDL_OPTS_PREVIEW``. Do not reintroduce
   a hardcoded player_client — a stale one is worse than none, since
   yt-dlp's own client selection is what keeps up with YouTube.

The video selector now explicitly asks for separate video+audio streams
(``bestvideo+bestaudio``), which is what the existing
``merge_output_format: mp4`` was always there to reassemble — the old
``best[ext=mp4]/best`` never requested them, so the merge had nothing to
do. (Stage 1 capped it by height with ``[height<=N][vcodec^=avc1]`` —
superseded below.)

**Day 11C (v2) — short side, not height.** Stage 0 diagnostics showed
the height cap degrading vertical video: a 1080x1920 Short asked for at
"720" came back 360x640, at "1080" 480x854. The selector is now
``bv*+ba/b`` with a format SORT — ``res:<short side>`` (yt-dlp's ``res``
is ``min(width, height)``), then the compatible codec, aac, mp4/m4a —
and ``res`` is omitted for ``VideoTier.BEST``. ``res`` is a soft
preference, not a cap: size protection stays with ``max_filesize`` plus
the pre-download size check (bug #5).

The compatible codec is ONE constant, ``_COMPATIBLE_VCODEC``, read by
both the download's ``format_sort`` and the preview's
``max_compatible_short_side`` — so the quality buttons a user is shown
are computed from exactly the formats the download will prefer (TikTok:
1080p exists only as h265, h264 tops out at 720p, so no quality step).

The spec crosses the spawn boundary as two primitives (kind value, tier
value or None) and is rebuilt in the child with ``spec_from_parts``.

**Day 11D-1 — media facts.** The delivery needs width, height and
duration to send a playable video (Telegram's guess from a bare document
is unpredictable). The child reads them from yt-dlp's FINAL info — after
the merge/transcode, so for ``bv*+ba`` they describe the merged file —
and runs ``ffprobe`` on the file only when info lacks one of them. They
travel back on the result queue as a JSON payload and come out of
``download()`` as a ``DownloadResult``.

**Preview timeout (ops minimum before beta).** yt-dlp's
``socket_timeout``/``retries`` bound each request, not the extraction:
a source that drips bytes, or DNS that never answers (``getaddrinfo``
ignores ``socket_timeout``), kept ``extract_info`` — and the executor
thread under it — busy indefinitely. The pool is bounded and, since Day
11C v2, ``/download`` goes through the preview too, so a few stalled
links starved the whole bot. A thread can't be killed, so the preview
now gets the same kill switch as the download: a child process,
``terminate()``'d (then ``kill()``'d) after ``preview_timeout_seconds``
— ``_collect_preview_result``, pinned by a real-process test.

The context is ``forkserver``, not ``spawn``: the bot runs as
``python -m src.main`` and a spawned child re-imports that whole module
(aiogram, SQLAlchemy, … — about 2 s) before doing anything. The
forkserver preloads this module and the parent's main module once (see
``_forkserver_preload``), so each preview child is a cheap fork of a
process that already has all of it imported. The download path keeps
``spawn``: it runs once per job in the worker, where a fraction of a
second is noise.

The child sends back only the preview facts (``_preview_facts``), never
yt-dlp's info dict — the full format list of a YouTube video is large
enough to make pickling it a cost of its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import multiprocessing
import os
import queue
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import yt_dlp

from src.domain.exceptions import (
    DownloadTimeoutError,
    ExtractionError,
    FileTooLargeError,
    PreviewTimeoutError,
)
from src.domain.interfaces.downloader import ProgressCallback
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.download_progress import DownloadProgress
from src.domain.value_objects.download_result import DownloadResult
from src.domain.value_objects.download_spec import (
    AudioSpec,
    DownloadSpec,
    VideoSpec,
    spec_from_parts,
    spec_kind,
    spec_video_tier,
)
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.format_kind import FormatKind
from src.domain.value_objects.media_preview import MediaPreview
from src.domain.value_objects.progress_phase import ProgressPhase
from src.infrastructure.downloader.error_classifier import classify_error
from src.shared.logging import describe_error, get_logger

logger = get_logger(__name__)

# Day 11C (v2): the video codec Telegram clients play inline. ONE
# definition with two readers — the download's `format_sort` and the
# preview's `max_compatible_short_side` — so the quality buttons can't be
# computed from formats the download wouldn't prefer. Spelled the way
# yt-dlp's `format_sort` spells it.
_COMPATIBLE_VCODEC = "h264"

# How each `format_sort` codec name appears in a format dict's `vcodec`
# (YouTube: "avc1.640028", TikTok: "h264"). Keyed by the sort name, so
# changing `_COMPATIBLE_VCODEC` changes the preview side with it.
_VCODEC_PREFIXES: dict[str, tuple[str, ...]] = {
    "h264": ("avc1", "h264"),
    "h265": ("hvc1", "hev1", "h265"),
    "vp9": ("vp9", "vp09"),
    "av01": ("av01",),
}


def _max_compatible_short_side(formats: list[dict[str, Any]]) -> int | None:
    """Largest ``min(width, height)`` among video formats in the
    compatible codec; among ALL video formats if the source has none in
    it; None if no video format reports its dimensions."""
    sized = [
        f
        for f in formats
        if f.get("vcodec") not in (None, "none") and f.get("width") and f.get("height")
    ]
    prefixes = _VCODEC_PREFIXES[_COMPATIBLE_VCODEC]
    compatible = [f for f in sized if str(f["vcodec"]).startswith(prefixes)]
    pool = compatible or sized
    if not pool:
        return None
    return max(min(int(f["width"]), int(f["height"])) for f in pool)


_YDL_OPTS_PREVIEW: dict[str, Any] = {
    "quiet": True,
    "socket_timeout": 30,
    "retries": 3,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    # No `extractor_args`/`player_client` here by design — see the module
    # docstring (Day 11C stage 1): the hardcoded android client was the
    # cause of the 360p-only format list, not a mitigation for it. If
    # 403s or missing formats appear again, update yt-dlp first
    # (`docker compose build --no-cache`) — do not pin a client.
}


def _video_tier_value(spec: DownloadSpec) -> str | None:
    tier = spec_video_tier(spec)
    return tier.value if tier is not None else None


def _extract_info_sync(url: str) -> dict[str, Any] | None:
    """Runs in the preview child process — see _preview_worker_entrypoint.
    Never call directly from async code."""
    with yt_dlp.YoutubeDL(_YDL_OPTS_PREVIEW) as ydl:
        info = ydl.extract_info(url, download=False)
        return dict(info) if info is not None else None


def _preview_facts(info: dict[str, Any]) -> dict[str, Any]:
    """The subset of yt-dlp's info that ``get_preview`` needs, as
    primitives — computed in the child, so the format list never crosses
    the process boundary."""
    return {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "thumbnail": info.get("thumbnail"),
        "media_type": _guess_media_type(info).value,
        "extractor_key": str(info.get("extractor_key") or "").lower(),
        "max_compatible_short_side": _max_compatible_short_side(info.get("formats") or []),
    }


def _preview_worker_entrypoint(
    url: str, result_queue: multiprocessing.Queue[tuple[str, Any]]
) -> None:
    """Child process entrypoint. Puts exactly one item on ``result_queue``:
    ``("ok", facts)``, ``("empty", None)`` when yt-dlp returned no info,
    ``("extract_error", message)`` for a yt-dlp ``DownloadError``, or
    ``("error", message)`` for anything else."""
    try:
        info = _extract_info_sync(url)
        if info is None:
            result_queue.put(("empty", None))
        else:
            result_queue.put(("ok", _preview_facts(info)))
    except yt_dlp.utils.DownloadError as exc:
        result_queue.put(("extract_error", str(exc)))
    except Exception as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _guess_media_type(info: dict[str, Any]) -> MediaType:
    if info.get("vcodec") not in (None, "none"):
        return MediaType.VIDEO
    if info.get("acodec") not in (None, "none"):
        return MediaType.AUDIO
    return MediaType.UNKNOWN


def _build_download_ydl_opts(
    output_dir: str,
    max_filesize_bytes: int | None,
    spec: DownloadSpec,
    post_hook: Any,
    progress_hook: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Assemble the ydl_opts for the real download.

    Day 11A: the ONLY difference between video and audio lives here — the
    format selection and (for audio) the ``FFmpegExtractAudio``
    postprocessor. Everything else (retries, timeouts, restrictfilenames,
    post_hooks) is identical across both, so it's built once and the
    format-specific keys are layered on top. This keeps the two paths
    from drifting: a retry/timeout tweak applies to both automatically.

    Day 11B: ``progress_hook`` (optional, defaults to no hook at all) is
    yt-dlp's own ``progress_hooks`` mechanism — distinct from
    ``post_hook``/``post_hooks``, which fires once at the very end.

    Day 11C (v2): takes the whole ``spec``. Video quality is a format
    SORT on the tier's short side, not a height filter — see the module
    docstring.
    """
    ydl_opts: dict[str, Any] = {
        "quiet": True,
        # `quiet` alone still draws the progress bar on stdout; progress
        # reaches the user through `progress_hooks`, so the bar is noise.
        "noprogress": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": f"{output_dir}/%(id)s.%(ext)s",
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        "post_hooks": [post_hook],
        "progress_hooks": [progress_hook] if progress_hook is not None else [],
    }

    match spec:
        case AudioSpec():
            # bestaudio, then transcode to mp3 via the system ffmpeg. The
            # postprocessor rewrites the extension; post_hooks reports the
            # real .mp3 path afterwards (bug #4), so no filename prediction.
            # `[ext=m4a]` first: prefer a real audio-only track over whatever
            # bare `bestaudio` resolves to, so we don't pull a full muxed
            # stream just to throw the video away in ffmpeg.
            ydl_opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": spec.codec.value,
                    "preferredquality": "192",
                }
            ]
        case VideoSpec(tier=tier):
            # Separate streams first (what merge_output_format reassembles),
            # any single file as the fallback. WHICH streams is decided by
            # the sort: closest to the tier's short side (no preference for
            # BEST), then the inline-playable codec, aac, mp4/m4a. The
            # audio track's language is not ours to sort: yt-dlp ranks the
            # original track above auto-dubs on its own (pinned by the
            # fixture tests — youtube_1080 carries 20 dubbed tracks).
            sort = [f"vcodec:{_COMPATIBLE_VCODEC}", "acodec:aac", "ext:mp4:m4a"]
            if tier.short_side is not None:
                sort.insert(0, f"res:{tier.short_side}")
            ydl_opts["format"] = "bv*+ba/b"
            ydl_opts["format_sort"] = sort
            ydl_opts["merge_output_format"] = "mp4"

    if max_filesize_bytes:
        # Also passed to yt-dlp itself as a backstop, but NOT relied
        # on as the primary mechanism: yt-dlp aborts silently (no
        # exception) when a download exceeds max_filesize, leaving a
        # partial .part file behind — that's exactly the bug this
        # class of "file missing after reported success" turned out
        # to be. The proactive check below (using extract_info
        # without downloading first) is the real fix: it fails fast,
        # with a clear reason, before any bytes are transferred.
        ydl_opts["max_filesize"] = max_filesize_bytes

    return ydl_opts


def _raise_classified(message: str, url: str) -> None:
    """Translate a raw yt-dlp error message into the matching domain
    exception and raise it. Never returns. The raw ``message`` is assumed
    to have ALREADY been logged by the caller — it is not put into the
    raised exception's user-facing text (bug #6); the exception's
    ``error_key`` is what the caller renders.
    """
    exc_type = classify_error(message, url)
    # A short, key-only construction — no diagnostic text in the message,
    # since callers surface error_key, not str(exc), to the user.
    raise exc_type()


class _DownloadTimeoutError(Exception):
    """Internal — raised by _run_download_in_process, caught by download()."""


class _DownloadProcessError(Exception):
    """Internal — raised by _run_download_in_process, caught by download().
    Carries a diagnostic-rich message meant for logs, not for the end
    user directly (see download()'s exception mapping)."""


class _PreviewTimeoutError(Exception):
    """Internal — raised by _collect_preview_result, caught by get_preview()."""


class _DownloadExtractError(Exception):
    """Internal — a yt-dlp DownloadError raised INSIDE the child process
    during the real download. Unlike _DownloadProcessError (our own
    diagnostics for the "file missing after success" class of bug), this
    wraps yt-dlp's own message so the parent can classify it into a
    domain category exactly as the preview path does. The raw text is for
    logs + classification only, never shown to the user."""


class _FileTooLargeError(Exception):
    """Internal — the video exceeds the configured size limit. Carries
    the estimated size and the limit (in MB) so the parent can raise the
    domain ``FileTooLargeError`` with those as localizable arguments —
    rather than a pre-baked, hardcoded-language string (the pre-Day-10
    approach embedded a Russian sentence right here in the child
    process, which couldn't be localized)."""

    def __init__(self, estimated_mb: int, limit_mb: int) -> None:
        super().__init__(f"file too large: ~{estimated_mb}MB > {limit_mb}MB")
        self.estimated_mb = estimated_mb
        self.limit_mb = limit_mb


def _estimate_total_filesize(info: dict[str, Any] | None) -> int | None:
    """Best-effort size estimate for the format(s) yt-dlp would actually
    fetch, using the same info structure produced by extract_info() with
    the same format selector as the real download. Returns None if no
    estimate is available (some formats/extractors don't report size) —
    callers must treat None as "unknown", not "zero".
    """
    if info is None:
        return None

    requested = info.get("requested_downloads")
    if requested:
        sizes = [r.get("filesize") or r.get("filesize_approx") for r in requested]
        if all(s is not None for s in sizes):
            return int(sum(sizes))
        return None

    size = info.get("filesize") or info.get("filesize_approx")
    return int(size) if size is not None else None


def _translate_progress_status(
    status: dict[str, Any], format_kind: FormatKind
) -> dict[str, Any] | None:
    """Pure decision logic for ``_record_progress`` (inside
    ``_download_worker_entrypoint``): given one raw yt-dlp progress-hook
    status dict, what (if anything) should land on ``progress_queue``?
    Returns ``None`` when nothing should be forwarded.

    Kept as a standalone module-level function — not inlined in the
    closure — specifically so this decision is unit-testable without
    spinning up a real child process, the same way ``_build_download_progress``
    is testable in isolation (Day 11B.1).
    """
    if status.get("status") == "finished":
        # Download→postprocess boundary. Audio-only: video has no
        # ffmpeg transcode step on its path worth announcing.
        if format_kind is FormatKind.AUDIO:
            return {"phase": ProgressPhase.CONVERTING}
        return None
    if status.get("status") != "downloading":
        return None
    return {
        "downloaded_bytes": status.get("downloaded_bytes"),
        "total_bytes": status.get("total_bytes") or status.get("total_bytes_estimate"),
        "speed": status.get("speed"),
        "eta": status.get("eta"),
    }


def _download_worker_entrypoint(
    url: str,
    output_dir: str,
    max_filesize_bytes: int | None,
    format_kind_value: str,
    video_tier_value: str | None,
    result_queue: multiprocessing.Queue[tuple[str, str]],
    progress_queue: multiprocessing.Queue[dict[str, Any]],
) -> None:
    """Entrypoint for the child process. This is the isolation boundary —
    everything yt-dlp/ffmpeg does happens here, in a process that can be
    killed independently of the worker's event loop.

    Must be a module-level function (not a closure/lambda): the "spawn"
    start method pickles the target, and closures aren't picklable. For
    the same reason ``format_kind`` crosses the boundary as its plain
    string value and is reconstructed into the enum here.

    Day 11B: ``progress_queue`` carries yt-dlp's own ``progress_hooks``
    events out to the parent — see the module docstring for the full
    bridge. ``status == "downloading"`` events are forwarded as-is.

    Day 11B.1: a ``status == "finished"`` event (fires once the download
    itself is done, before any postprocessing) is forwarded too, but only
    for AUDIO downloads and only as a bare phase marker
    ``{"phase": ProgressPhase.CONVERTING}`` — it carries no byte/percent
    data, just the boundary signal. VIDEO downloads still discard it:
    there's no ffmpeg transcode step on that path worth announcing.

    Day 11C (v2): the spec crosses the boundary as the same two
    primitives it is persisted as (``format_kind_value`` and
    ``video_tier_value``) and is rebuilt here with ``spec_from_parts`` —
    pickle-safe, and one strict parser for both the DB and this boundary.
    """
    try:
        # `post_hooks` is yt-dlp's own documented mechanism for exactly
        # this problem: it's called with the REAL final filename, after
        # every postprocessor (merger, remuxer, audio-extract, etc.) has
        # finished — not a prediction from the pre-download info dict.
        final_filenames: list[str] = []

        def _record_final_filename(filename: str) -> None:
            final_filenames.append(filename)

        def _record_progress(status: dict[str, Any]) -> None:
            raw = _translate_progress_status(status, format_kind)
            if raw is None:
                return
            # progress reporting must never break the download itself.
            with contextlib.suppress(Exception):
                progress_queue.put_nowait(raw)

        spec = spec_from_parts(format_kind_value, video_tier_value)
        format_kind = spec_kind(spec)
        ydl_opts = _build_download_ydl_opts(
            output_dir=output_dir,
            max_filesize_bytes=max_filesize_bytes,
            spec=spec,
            post_hook=_record_final_filename,
            progress_hook=_record_progress,
        )

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if max_filesize_bytes:
                preview_info = ydl.extract_info(url, download=False)
                estimated_size = _estimate_total_filesize(preview_info)
                if estimated_size is not None and estimated_size > max_filesize_bytes:
                    raise _FileTooLargeError(
                        estimated_mb=round(estimated_size / (1024 * 1024)),
                        limit_mb=max_filesize_bytes // (1024 * 1024),
                    )

            info = ydl.extract_info(url, download=True)

        used_post_hook_filename = bool(final_filenames)
        if final_filenames:
            filename = final_filenames[-1]
        else:
            # post_hooks didn't fire (shouldn't normally happen for a
            # successful download) — fall back to the best-effort guess
            # rather than failing outright.
            filename = _resolve_downloaded_filepath(ydl, info)

        if not os.path.isfile(filename):
            raise _DownloadProcessError(
                _build_missing_file_diagnostic(
                    filename=filename,
                    output_dir=output_dir,
                    used_post_hook_filename=used_post_hook_filename,
                    post_hook_filenames=final_filenames,
                    info=info,
                )
            )
        result_queue.put(("ok", json.dumps(_media_facts(info, filename, format_kind))))
    except _FileTooLargeError as exc:
        # Encode the two integers into the string payload (the queue's
        # value type is a plain string) as "estimated:limit"; the parent
        # splits them back out.
        result_queue.put(("too_large", f"{exc.estimated_mb}:{exc.limit_mb}"))
    except yt_dlp.utils.DownloadError as exc:
        # yt-dlp's own failure (private/geo/age/removed/unsupported-media,
        # or a transient network error). Send the raw text back tagged as
        # "extract_error" so the PARENT can classify it into a domain
        # category — classification can't happen here because the domain
        # exception types shouldn't be pickled across the process
        # boundary; the message is the reliable carrier (see classifier).
        result_queue.put(("extract_error", str(exc)))
    except Exception as exc:  # noqa: BLE001 — must report every failure to the parent, never die silently
        result_queue.put(("error", str(exc)))


def _media_facts(
    info: dict[str, Any] | None, filename: str, format_kind: FormatKind
) -> dict[str, Any]:
    """The facts the delivery needs, from the final info dict; ffprobe on
    the file fills only what info lacks. Runs in the child."""
    info = info or {}
    is_video = format_kind is FormatKind.VIDEO
    width = _positive_int(info.get("width")) if is_video else None
    height = _positive_int(info.get("height")) if is_video else None
    duration = _positive_int(info.get("duration"))
    if duration is None or (is_video and (width is None or height is None)):
        probed = _ffprobe_facts(filename)
        duration = duration or probed.get("duration")
        if is_video:
            width = width or probed.get("width")
            height = height or probed.get("height")
    return {
        "path": filename,
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "title": info.get("title") or None,
        "uploader": info.get("artist") or info.get("uploader") or info.get("channel") or None,
    }


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return round(value)


def _ffprobe_facts(filename: str) -> dict[str, int]:
    """Fallback only. Any failure (no ffprobe, unreadable file, timeout)
    yields no facts — the delivery then degrades to a document, which is
    still a delivery."""
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,width,height:format=duration",
                "-of",
                "json",
                filename,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
        probe = json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    facts: dict[str, int] = {}
    streams: list[dict[str, Any]] = probe.get("streams", [])
    video = next((st for st in streams if st.get("codec_type") == "video"), {})
    for key in ("width", "height"):
        if (number := _positive_int(video.get(key))) is not None:
            facts[key] = number
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    if (seconds := _positive_int(duration)) is not None:
        facts["duration"] = seconds
    return facts


def _parse_result(payload: str) -> DownloadResult:
    facts = json.loads(payload)
    return DownloadResult(
        path=Path(facts["path"]),
        width=facts.get("width"),
        height=facts.get("height"),
        duration_seconds=facts.get("duration_seconds"),
        title=facts.get("title"),
        uploader=facts.get("uploader"),
    )


def _build_missing_file_diagnostic(
    *,
    filename: str,
    output_dir: str,
    used_post_hook_filename: bool,
    post_hook_filenames: list[str],
    info: dict[str, Any] | None,
) -> str:
    """Builds a diagnostic-rich error message for the "file missing after
    reported success" case. This case has recurred multiple times for the
    same video with different guesses at the root cause each time —
    guessing a fourth time isn't useful. Instead, this captures ground
    truth (actual directory contents, what post_hooks actually returned,
    the relevant `info` fields) so the *next* occurrence's log message
    contains enough to diagnose it directly, without needing another
    round-trip of "please send me the logs".
    """
    try:
        actual_files = os.listdir(output_dir)
    except OSError as exc:
        actual_files = [f"<could not list directory: {exc}>"]

    info_summary: dict[str, Any] | None = None
    if info is not None:
        info_summary = {
            "id": info.get("id"),
            "ext": info.get("ext"),
            "requested_downloads": info.get("requested_downloads"),
            "requested_formats": info.get("requested_formats"),
            "_filename": info.get("_filename"),
            "filepath": info.get("filepath"),
        }

    return (
        f"yt-dlp reported success but the output file is missing: {filename}. "
        f"used_post_hook_filename={used_post_hook_filename} "
        f"post_hook_filenames={post_hook_filenames!r} "
        f"dir_contents={actual_files!r} "
        f"info_summary={info_summary!r}"
    )


def _resolve_downloaded_filepath(ydl: yt_dlp.YoutubeDL, info: dict[str, Any] | None) -> str:
    """Fallback only — the primary mechanism is `post_hooks` (see
    _download_worker_entrypoint), which is more reliable. This function
    is used only if post_hooks unexpectedly didn't fire.

    Tries `info["requested_downloads"]` first (yt-dlp's per-entry final
    path, when populated), then falls back to `ydl.prepare_filename()`
    — which predicts the filename from pre-download/pre-merge info and
    is known to be unreliable when yt-dlp merges separate video+audio
    streams via ffmpeg (the container/path can differ from the
    prediction). Kept as a last resort, not the primary path.
    """
    if info is None:
        raise _DownloadProcessError("yt-dlp returned no info after download")

    requested = info.get("requested_downloads")
    if requested:
        filepath = requested[0].get("filepath")
        if filepath:
            return str(filepath)

    # Fallback for the rare case requested_downloads isn't populated
    # (e.g. some extractors/edge cases) — best-effort, matches the
    # pre-Day-5.1 behavior, kept only as a last resort.
    return str(ydl.prepare_filename(info))


def _build_download_progress(raw: dict[str, Any]) -> DownloadProgress:
    """Pure mapping: a raw progress-hook dict (as put on progress_queue by
    the child, see _download_worker_entrypoint) → the domain
    ``DownloadProgress`` value object. ``percent`` is None whenever
    ``total_bytes`` is None (a stream yt-dlp can't size up front) —
    callers render bytes/speed instead in that case.

    Day 11B.1: a ``{"phase": ProgressPhase.CONVERTING}`` marker (no byte
    fields at all) maps to a snapshot with everything else blank —
    callers must check ``phase`` before touching the numeric fields.
    """
    if raw.get("phase") == ProgressPhase.CONVERTING:
        return DownloadProgress(
            percent=None,
            downloaded_bytes=0,
            total_bytes=None,
            speed=None,
            eta=None,
            phase=ProgressPhase.CONVERTING,
        )

    downloaded = int(raw.get("downloaded_bytes") or 0)
    total_raw = raw.get("total_bytes")
    total_bytes = int(total_raw) if total_raw is not None else None
    speed_raw = raw.get("speed")
    eta_raw = raw.get("eta")
    percent = (downloaded / total_bytes * 100) if total_bytes else None
    return DownloadProgress(
        percent=percent,
        downloaded_bytes=downloaded,
        total_bytes=total_bytes,
        speed=float(speed_raw) if speed_raw is not None else None,
        eta=int(eta_raw) if eta_raw is not None else None,
    )


def _wait_and_drain_progress(
    process: multiprocessing.process.BaseProcess,
    progress_queue: multiprocessing.Queue[dict[str, Any]],
    progress_sink: Callable[[dict[str, Any] | None], None] | None,
    timeout_seconds: int,
) -> None:
    """Blocks the CALLING thread (must be an executor thread, never the
    event loop) until `process` exits or `timeout_seconds` elapses,
    whichever first — draining `progress_queue` into `progress_sink`
    (when given) along the way instead of one long `process.join(timeout)`.

    This is the ONE place the Day 5 terminate-by-timeout contract lives:
    on timeout, `process.terminate()` + `process.join(5)` +
    `_DownloadTimeoutError`, byte-for-byte the same as before Day 11B —
    see tests/unit/test_process_kill_mechanism.py, which calls this
    function directly (not a hand-copied mirror) against a real spawned
    process to pin exactly this guarantee.
    """
    deadline = time.monotonic() + timeout_seconds
    while process.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = progress_queue.get(timeout=min(0.5, remaining))
        except queue.Empty:
            continue
        if progress_sink is not None:
            progress_sink(raw)

    if process.is_alive():
        process.terminate()
        process.join(5)
        raise _DownloadTimeoutError(
            f"Download exceeded the {timeout_seconds} s limit and was aborted"
        )

    process.join()  # already exited — reap the zombie, effectively instant


def _stop_process(process: multiprocessing.process.BaseProcess) -> None:
    """SIGTERM, then SIGKILL if the child is still there 5 s later — the
    executor thread waiting on it must come back in bounded time."""
    process.terminate()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join()


def _collect_preview_result(
    process: multiprocessing.process.BaseProcess,
    result_queue: multiprocessing.Queue[tuple[str, Any]],
    timeout_seconds: float,
) -> tuple[str, Any]:
    """Blocks the CALLING thread (an executor thread) until the preview
    child reports its one result or ``timeout_seconds`` elapses. On
    timeout the child is stopped and ``_PreviewTimeoutError`` raised; a
    child that exits without a result raises ``_DownloadProcessError``
    right away instead of waiting out the timeout.

    Reads the queue BEFORE joining: a child whose queued item hasn't been
    flushed into the pipe can't exit, so join-then-read can deadlock.
    """
    deadline = time.monotonic() + timeout_seconds
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            item = result_queue.get(timeout=min(0.5, remaining))
        except queue.Empty:
            if process.is_alive():
                continue
            # Exited. A child flushes its queue before it exits, so a
            # result it did put is in the pipe by now.
            try:
                item = result_queue.get(timeout=0.1)
            except queue.Empty:
                process.join()
                raise _DownloadProcessError(
                    f"Preview process exited without a result (exit code {process.exitcode})"
                ) from None
        process.join(5)
        if process.is_alive():
            _stop_process(process)
        return item

    _stop_process(process)
    raise _PreviewTimeoutError(f"Preview exceeded the {timeout_seconds} s limit and was aborted")


def _forkserver_preload() -> list[str]:
    """Every forkserver child still re-runs the parent's main module
    (multiprocessing's "main fixup", same as spawn). Preloading that
    module too leaves the re-run only its top-level definitions to do —
    its imports are already in the server."""
    main_spec = getattr(sys.modules["__main__"], "__spec__", None)
    main_name = getattr(main_spec, "name", None)
    if main_name is None or main_name.endswith("__main__"):
        # A script (or `python -m pkg`): the forkserver loads it by path.
        main_name = "__main__"
    return [main_name, __name__]


def _preview_context() -> multiprocessing.context.ForkServerContext:
    ctx = multiprocessing.get_context("forkserver")
    # Takes effect when the forkserver starts (the first preview); later
    # calls change nothing. See the module docstring for why not spawn.
    ctx.set_forkserver_preload(_forkserver_preload())
    return ctx


class RunPreviewInProcess(Protocol):
    """The call shape of ``_run_preview_in_process`` — same purpose as
    ``RunDownloadInProcess`` below."""

    def __call__(self, url: str, timeout_seconds: int, /) -> dict[str, Any] | None: ...


def _run_preview_in_process(url: str, timeout_seconds: int) -> dict[str, Any] | None:
    """Blocking. Must only be called via loop.run_in_executor(). Returns
    the preview facts, or None when yt-dlp found nothing."""
    ctx = _preview_context()
    result_queue: multiprocessing.Queue[tuple[str, Any]] = ctx.Queue()
    process = ctx.Process(target=_preview_worker_entrypoint, args=(url, result_queue))
    process.start()

    status, payload = _collect_preview_result(process, result_queue, timeout_seconds)
    if status == "extract_error":
        raise _DownloadExtractError(payload)
    if status == "error":
        raise _DownloadProcessError(payload)
    facts: dict[str, Any] | None = payload
    return facts


_PREVIEW_RUNNER_CONTRACT: RunPreviewInProcess = _run_preview_in_process


class RunDownloadInProcess(Protocol):
    """The exact call shape of ``_run_download_in_process`` — positional,
    because ``run_in_executor`` passes it that way.

    Tests replace the runner with fakes; annotating them with this
    protocol lets mypy flag a fake that drifts from the real signature.
    One already did silently: a stand-in with the pre-v2 argument order
    took the tier string as its ``progress_sink``, and the progress drain
    waited forever instead of failing.
    """

    def __call__(
        self,
        url: str,
        output_dir: str,
        max_filesize_bytes: int | None,
        timeout_seconds: int,
        format_kind_value: str,
        video_tier_value: str | None,
        progress_sink: Callable[[dict[str, Any] | None], None] | None = None,
        /,
    ) -> DownloadResult: ...


def _run_download_in_process(
    url: str,
    output_dir: str,
    max_filesize_bytes: int | None,
    timeout_seconds: int,
    format_kind_value: str,
    video_tier_value: str | None,
    progress_sink: Callable[[dict[str, Any] | None], None] | None = None,
) -> DownloadResult:
    """Blocking. Must only be called via loop.run_in_executor() — never
    directly on the event loop thread. The blocking work here
    (`_wait_and_drain_progress`) is cheap waiting/polling, not CPU work;
    the actual yt-dlp/ffmpeg work happens in the child process.

    Day 11B: sends a final `progress_sink(None)` in a `finally` — see
    `_drain_bridge`'s docstring for why THIS function (not `download()`)
    must be the one to signal "no more progress events are coming".

    Day 11C (v2): the spec primitives are forwarded verbatim into the
    child's args tuple. Nothing about the timeout/terminate contract in
    `_wait_and_drain_progress` changes.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue[tuple[str, str]] = ctx.Queue()
    progress_queue: multiprocessing.Queue[dict[str, Any]] = ctx.Queue()
    process = ctx.Process(
        target=_download_worker_entrypoint,
        args=(
            url,
            output_dir,
            max_filesize_bytes,
            format_kind_value,
            video_tier_value,
            result_queue,
            progress_queue,
        ),
    )
    process.start()

    try:
        _wait_and_drain_progress(process, progress_queue, progress_sink, timeout_seconds)
    finally:
        if progress_sink is not None:
            progress_sink(None)

    if result_queue.empty():
        raise _DownloadProcessError(f"Download process crashed (exit code {process.exitcode})")

    status, payload = result_queue.get()
    if status == "too_large":
        estimated_str, limit_str = payload.split(":", 1)
        raise _FileTooLargeError(estimated_mb=int(estimated_str), limit_mb=int(limit_str))
    if status == "extract_error":
        raise _DownloadExtractError(payload)
    if status == "error":
        raise _DownloadProcessError(payload)
    return _parse_result(payload)


# The real runner must satisfy its own protocol (checked by mypy on src).
_RUNNER_CONTRACT: RunDownloadInProcess = _run_download_in_process


async def _drain_bridge(
    bridge: asyncio.Queue[dict[str, Any] | None], progress_callback: ProgressCallback
) -> None:
    """Runs entirely on the event loop (an asyncio.Task) — the only thing
    that ever touches `progress_callback` directly. `bridge` is fed
    exclusively via `loop.call_soon_threadsafe(bridge.put_nowait, raw)`
    from the executor thread (see download()), so this side is plain
    single-threaded async code: no locks, no thread-safety concerns,
    trivially unit-testable by just putting items on a real asyncio.Queue.

    Stops on `None`. Day 11B originally had `download()` push a stop
    sentinel itself right after `run_in_executor` returned — that's
    WRONG and was caught by a flaky test: `download()` resuming (via the
    executor future's own completion callback) is a SEPARATE scheduling
    path from `progress_sink`'s `call_soon_threadsafe` calls, and nothing
    guarantees the latter has already landed in `bridge` by the time the
    former fires — under load the stop signal could overtake the very
    last real item. The fix: the STOP marker travels through the exact
    same channel (`progress_sink`, called from the SAME executor thread,
    in `_run_download_in_process`'s `finally`) as every real item, so
    plain same-thread `call_soon_threadsafe` submission order — which
    IS guaranteed — keeps it correctly last.
    """
    while True:
        raw = await bridge.get()
        if raw is None:
            return
        await progress_callback(_build_download_progress(raw))


class YtDlpDownloader:
    def __init__(self, *, preview_timeout_seconds: int) -> None:
        self._preview_timeout_seconds = preview_timeout_seconds

    async def get_preview(self, url: str) -> MediaPreview:
        loop = asyncio.get_running_loop()

        try:
            facts = await loop.run_in_executor(
                None, _run_preview_in_process, url, self._preview_timeout_seconds
            )
        except _PreviewTimeoutError as exc:
            logger.warning(
                "preview_extraction_failed", url=url, error=describe_error(exc), reason="timeout"
            )
            raise PreviewTimeoutError from exc
        except _DownloadExtractError as exc:
            # Log the full diagnostic message, then raise a CATEGORIZED
            # domain error carrying only a semantic key — never the raw
            # text (bug #6).
            logger.warning("preview_extraction_failed", url=url, error=describe_error(exc))
            _raise_classified(str(exc), url)
        except _DownloadProcessError as exc:
            logger.warning(
                "preview_extraction_failed",
                url=url,
                error=describe_error(exc),
                reason="process_error",
            )
            raise ExtractionError from exc

        if facts is None:
            logger.warning("preview_extraction_empty_result", url=url)
            raise ExtractionError

        return MediaPreview(
            source_url=url,
            title=facts["title"] or None,
            duration_seconds=facts["duration"],
            uploader=facts["uploader"],
            thumbnail_url=facts["thumbnail"],
            media_type=MediaType(facts["media_type"]),
            # Day 11C (v2): both from the extractor's own result — the
            # preview is the only trusted source for them (see
            # PreviewContext).
            extractor_key=facts["extractor_key"],
            max_compatible_short_side=facts["max_compatible_short_side"],
        )

    async def download(
        self,
        url: str,
        options: DownloadOptions,
        progress_callback: ProgressCallback | None = None,
    ) -> DownloadResult:
        loop = asyncio.get_running_loop()
        options.output_dir.mkdir(parents=True, exist_ok=True)

        # Day 11B: see the module docstring for the two-hop bridge this
        # sets up. `bridge`/`drain_task` only exist when the caller
        # actually wants progress — no cost for callers that don't pass
        # progress_callback (e.g. get_preview's callers, or any test that
        # doesn't care about progress).
        bridge: asyncio.Queue[dict[str, Any] | None] | None = None
        progress_sink: Callable[[dict[str, Any] | None], None] | None = None
        drain_task: asyncio.Task[None] | None = None
        if progress_callback is not None:
            bridge = asyncio.Queue()
            _bridge = bridge  # local alias so mypy narrows it as non-Optional in the closure

            def _sink(raw: dict[str, Any] | None) -> None:
                loop.call_soon_threadsafe(_bridge.put_nowait, raw)

            progress_sink = _sink
            drain_task = asyncio.create_task(_drain_bridge(bridge, progress_callback))

        try:
            result = await loop.run_in_executor(
                None,
                _run_download_in_process,
                url,
                str(options.output_dir),
                options.max_filesize_bytes,
                options.timeout_seconds,
                # Day 11C (v2): the spec as primitives (pickle-safe across
                # the spawn boundary), never the dataclass itself.
                spec_kind(options.spec).value,
                _video_tier_value(options.spec),
                progress_sink,
            )
        except _DownloadTimeoutError as exc:
            logger.warning("download_failed", url=url, error=describe_error(exc), reason="timeout")
            # Timeout has its own dedicated key — it's neither a content
            # problem nor a generic extraction failure.
            raise DownloadTimeoutError from exc
        except _FileTooLargeError as exc:
            logger.warning(
                "download_failed", url=url, error=describe_error(exc), reason="too_large"
            )
            # Domain FileTooLargeError carries the numbers as localizable
            # arguments (error-too-large FTL key), not a pre-baked string.
            raise FileTooLargeError(estimated_mb=exc.estimated_mb, limit_mb=exc.limit_mb) from exc
        except _DownloadExtractError as exc:
            # A yt-dlp failure during the real download — classify it into
            # the same domain categories the preview path uses. Raw text
            # to the log only.
            logger.warning(
                "download_failed", url=url, error=describe_error(exc), reason="extract_error"
            )
            _raise_classified(str(exc), url)
        except _DownloadProcessError as exc:
            # `str(exc)` here may be a diagnostic-rich message (container
            # paths, yt-dlp internals, occasionally signed CDN URLs) —
            # that belongs in the log, not in a message sent to the user.
            logger.warning(
                "download_failed", url=url, error=describe_error(exc), reason="process_error"
            )
            raise ExtractionError from exc
        finally:
            # `_run_download_in_process` itself sends the None stop
            # marker (via progress_sink, from the executor thread — see
            # _drain_bridge's docstring for why it must be that thread
            # and not here) before returning, so by the time
            # run_in_executor's await above resolves, drain_task is
            # already guaranteed to run to completion on its own.
            if drain_task is not None:
                await drain_task

        logger.info(
            "download_succeeded",
            url=url,
            path=str(result.path),
            width=result.width,
            height=result.height,
            duration_seconds=result.duration_seconds,
        )
        return result
