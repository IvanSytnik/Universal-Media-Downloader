# ADR 0003: Preview extraction runs in a killable child process

- Status: accepted
- Date: 2026-10-26
- Scope: ops minimum before beta, item 1

## Context

`get_preview` ran `yt_dlp.extract_info` on the default thread pool,
bounded only by `socket_timeout=30` and `retries=3`. Those bound each
request, not the extraction: a source that drips bytes under the socket
timeout, a long chain of requests, or DNS that never answers
(`getaddrinfo` ignores `socket_timeout`) keeps the call — and the thread
under it — busy with no upper limit. The pool is bounded
(`min(32, cpu + 4)`), and since Day 11C v2 `/download` goes through the
preview as well, so a handful of stalled links would stop the bot from
answering any link at all.

`asyncio.wait_for` around `run_in_executor` only stops *waiting*: Python
cannot kill a thread, so the stalled extraction keeps its pool slot.
That fixes the user's wait and not the exhaustion.

## Decision

1. The preview extraction runs in a child process, one per preview, with
   the same kill switch as the download (Day 5): `_collect_preview_result`
   waits at most `preview_timeout_seconds` (setting, default 60), then
   `terminate()`, and `kill()` if the child is still alive 5 s later. The
   executor thread is back within `timeout + 5 s` in every case.
2. Timeout maps to a new domain error, `PreviewTimeoutError`
   (`ExtractionError` subclass, `error-preview-timeout`), so every
   handler that already catches `ExtractionError` handles it. A child
   that dies without a result is a generic `ExtractionError`, reported
   immediately rather than at the deadline.
3. The context is `forkserver` with the parent's main module and the
   downloader module preloaded. `spawn` re-imports the bot's `src.main`
   in every child (measured ~2.4 s per preview); forkserver children
   still re-run the main module, but against imports already cached in
   the server (measured ~0.3 s total overhead, most of it yt-dlp
   compiling extractor URL regexes). The download path stays on `spawn`.
4. The child returns only the preview facts (title, duration, uploader,
   thumbnail, media type, extractor key, compatible short side) as
   primitives, never the info dict with its format list.

## Consequences

- Hard upper bound on preview latency and on thread occupancy; a hung
  extraction costs one process for at most `timeout + 5 s`.
- ~0.3 s added to every preview, and a long-lived forkserver process in
  the bot container (started on the first preview).
- The first preview after start pays the forkserver start (~2.4 s: one
  import of the bot's module graph).
- Unit tests patch `_run_preview_in_process` (typed against
  `RunPreviewInProcess`); `tests/unit/test_preview_kill_mechanism.py`
  drives real forkserver children through the shipped wait/kill code.
- Not done: warming yt-dlp's extractor regexes in the forkserver (would
  save 50–200 ms per preview), and a concurrency cap on previews — the
  per-user rate limit (5/min) is the only one today.
