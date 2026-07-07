"""yt-dlp implementation of DownloaderPort.

Uses yt-dlp's native Python API (`yt_dlp.YoutubeDL`), not a CLI subprocess
wrapper — decided in PROJECT_SPEC §6.4.

**Why `download()` spawns a fresh process per call (Day 5):**

`get_preview()` (Day 4) runs `extract_info` in the default thread pool —
fine for a quick metadata lookup. Real downloads are long-running and
must be cancellable with a hard guarantee: if a download hangs (dead
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
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from pathlib import Path
from typing import Any

import yt_dlp

from src.domain.exceptions import ExtractionError
from src.domain.value_objects.download_options import DownloadOptions
from src.domain.value_objects.enums import MediaType
from src.domain.value_objects.media_preview import MediaPreview
from src.shared.logging import get_logger

logger = get_logger(__name__)

_YDL_OPTS_PREVIEW: dict[str, Any] = {
    "quiet": True,
    "socket_timeout": 30,
    "retries": 3,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    # YouTube periodically tightens bot detection, which shows up as
    # HTTP 403 during download (extract_info for preview is less
    # affected — that's why /preview kept working while /download
    # started failing). Requesting the android client is a common,
    # best-effort mitigation, not a permanent fix: YouTube changes this
    # regularly, and yt-dlp itself needs frequent updates to keep up.
    # If 403s return, the first thing to try is `docker compose build
    # --no-cache` to pull the latest yt-dlp, then revisit this.
    "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
}


def _extract_info_sync(url: str) -> dict[str, Any] | None:
    """Runs on a worker thread — see get_preview(). Never call directly
    from async code."""
    with yt_dlp.YoutubeDL(_YDL_OPTS_PREVIEW) as ydl:
        info = ydl.extract_info(url, download=False)
        return dict(info) if info is not None else None


def _guess_media_type(info: dict[str, Any]) -> MediaType:
    if info.get("vcodec") not in (None, "none"):
        return MediaType.VIDEO
    if info.get("acodec") not in (None, "none"):
        return MediaType.AUDIO
    return MediaType.UNKNOWN


class _DownloadTimeoutError(Exception):
    """Internal — raised by _run_download_in_process, caught by download()."""


class _DownloadProcessError(Exception):
    """Internal — raised by _run_download_in_process, caught by download().
    Carries a diagnostic-rich message meant for logs, not for the end
    user directly (see download()'s exception mapping)."""


class _FileTooLargeError(Exception):
    """Internal — the video exceeds the configured size limit. Unlike
    _DownloadProcessError, this message IS safe and meaningful to show
    the end user directly."""


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


def _download_worker_entrypoint(
    url: str,
    output_dir: str,
    max_filesize_bytes: int | None,
    result_queue: multiprocessing.Queue[tuple[str, str]],
) -> None:
    """Entrypoint for the child process. This is the isolation boundary —
    everything yt-dlp/ffmpeg does happens here, in a process that can be
    killed independently of the worker's event loop.

    Must be a module-level function (not a closure/lambda): the "spawn"
    start method pickles the target, and closures aren't picklable.
    """
    try:
        # `post_hooks` is yt-dlp's own documented mechanism for exactly
        # this problem: it's called with the REAL final filename, after
        # every postprocessor (merger, remuxer, etc.) has finished —
        # not a prediction from the pre-download info dict.
        final_filenames: list[str] = []

        def _record_final_filename(filename: str) -> None:
            final_filenames.append(filename)

        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "outtmpl": f"{output_dir}/%(id)s.%(ext)s",
            "format": "best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "continuedl": True,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "post_hooks": [_record_final_filename],
        }
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

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if max_filesize_bytes:
                preview_info = ydl.extract_info(url, download=False)
                estimated_size = _estimate_total_filesize(preview_info)
                if estimated_size is not None and estimated_size > max_filesize_bytes:
                    size_mb = estimated_size / (1024 * 1024)
                    limit_mb = max_filesize_bytes // (1024 * 1024)
                    raise _FileTooLargeError(
                        f"Видео слишком большое для отправки в Telegram "
                        f"(~{size_mb:.0f} МБ, лимит {limit_mb} МБ)"
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
        result_queue.put(("ok", filename))
    except _FileTooLargeError as exc:
        result_queue.put(("too_large", str(exc)))
    except Exception as exc:  # noqa: BLE001 — must report every failure to the parent, never die silently
        result_queue.put(("error", str(exc)))


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


def _run_download_in_process(
    url: str,
    output_dir: str,
    max_filesize_bytes: int | None,
    timeout_seconds: int,
) -> str:
    """Blocking. Must only be called via loop.run_in_executor() — never
    directly on the event loop thread. The blocking call here is
    `process.join(timeout)`, which is cheap (just waiting), not CPU work;
    the actual yt-dlp/ffmpeg work happens in the child process.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue[tuple[str, str]] = ctx.Queue()
    process = ctx.Process(
        target=_download_worker_entrypoint,
        args=(url, output_dir, max_filesize_bytes, result_queue),
    )
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(5)
        raise _DownloadTimeoutError(
            f"Скачивание превысило лимит {timeout_seconds} секунд и было прервано"
        )

    if result_queue.empty():
        raise _DownloadProcessError(
            f"Процесс скачивания завершился аварийно (exit code {process.exitcode})"
        )

    status, payload = result_queue.get()
    if status == "too_large":
        raise _FileTooLargeError(payload)
    if status == "error":
        raise _DownloadProcessError(payload)
    return payload


class YtDlpDownloader:
    async def get_preview(self, url: str) -> MediaPreview:
        loop = asyncio.get_running_loop()

        try:
            info = await loop.run_in_executor(None, _extract_info_sync, url)
        except yt_dlp.utils.DownloadError as exc:
            logger.warning("preview_extraction_failed", url=url, error=str(exc))
            raise ExtractionError(f"Не удалось получить информацию о видео: {exc}") from exc

        if info is None:
            logger.warning("preview_extraction_empty_result", url=url)
            raise ExtractionError("yt-dlp вернул пустой результат для этой ссылки")

        return MediaPreview(
            source_url=url,
            title=info.get("title") or "Без названия",
            duration_seconds=info.get("duration"),
            uploader=info.get("uploader"),
            thumbnail_url=info.get("thumbnail"),
            media_type=_guess_media_type(info),
        )

    async def download(self, url: str, options: DownloadOptions) -> Path:
        loop = asyncio.get_running_loop()
        options.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            result_path_str = await loop.run_in_executor(
                None,
                _run_download_in_process,
                url,
                str(options.output_dir),
                options.max_filesize_bytes,
                options.timeout_seconds,
            )
        except _DownloadTimeoutError as exc:
            logger.warning("download_failed", url=url, error=str(exc), reason="timeout")
            raise ExtractionError(
                "Скачивание заняло слишком много времени и было прервано"
            ) from exc
        except _FileTooLargeError as exc:
            # This message is safe to show the user as-is — it was built
            # specifically for that purpose (see _FileTooLargeError).
            logger.warning("download_failed", url=url, error=str(exc), reason="too_large")
            raise ExtractionError(str(exc)) from exc
        except _DownloadProcessError as exc:
            # `str(exc)` here may be a diagnostic-rich message (container
            # paths, yt-dlp internals, occasionally signed CDN URLs) —
            # that belongs in the log, not in a message sent to the user.
            # Keep it out of ExtractionError's text, which the caller
            # forwards straight into a Telegram message.
            logger.warning("download_failed", url=url, error=str(exc), reason="process_error")
            raise ExtractionError(
                "Не удалось скачать это видео. Попробуй другую ссылку."
            ) from exc

        logger.info("download_succeeded", url=url, path=result_path_str)
        return Path(result_path_str)
