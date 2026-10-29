# Architecture

This document explains how Universal Media Downloader is put together and
why. The decisions that were contested at the time are recorded as ADRs in
[`docs/adr/`](adr/); this page is the map that ties them together. Code
comments point here by section name (for example "architecture.md, Two-phase
flow") and by pitfall number ("bug #6").

## Layers and the dependency rule

```
src/
  domain/          entities, value objects, ports (Protocols), exceptions
  application/     use cases and policies; depends on domain only
  infrastructure/  adapters: PostgreSQL, Redis, arq, yt-dlp, Telegram client
  presentation/    aiogram handlers, keyboards, i18n, progress listener
  shared/          cross-cutting kernel: structured logging
  config/          pydantic-settings Settings
  composition.py, main.py   composition roots
```

Dependencies point inwards:

- **domain** imports the standard library and itself. It knows nothing
  about yt-dlp, Telegram, SQL or languages.
- **application** imports domain, application and `src.shared`.
- **presentation** imports anything except `src.infrastructure`; adapters
  reach it through the composition root.
- **infrastructure** implements domain ports.

The rule is enforced, not just documented:
[`tests/unit/test_architecture.py`](../tests/unit/test_architecture.py)
parses every module under `src/` with `ast`, counts imports inside
`if TYPE_CHECKING:` too, and tests its own scanner against every import
form.

Documented exceptions:

1. **application → `src.shared.logging`.** Use cases log through a thin
   wrapper over structlog (`get_logger`, `bind_log_context`,
   `describe_error`). Logging is cross-cutting; a logging port for every use
   case would add indirection without a second implementation to justify it.
   The cost is that application depends on structlog transitively.
2. **`infrastructure/queue/worker_settings.py` → `presentation.telegram.i18n`.**
   This module is the worker's composition root (arq loads it by dotted
   path), so like `main.py` and `composition.py` it wires concrete pieces
   together. It builds the same Fluent core the bot uses, so the worker's
   failure messages are localized from the same FTL files.

### Ports

`src/domain/interfaces/` defines the ports the application layer talks to:
`DownloaderPort`, `NotifierPort`, `StoragePort`, `TaskQueue`,
`ProgressPublisherPort`, `PreviewContextStorePort`, `RateLimiterPort`,
`ErrorLocalizerPort`, `HealthCheckPort`, `PingResultReader`,
`DownloadRequestRepository`, `UserRepository`. Each has one production
adapter in `src/infrastructure/` and one or more fakes in the tests.

## Two-phase flow

A download is two user actions, not one:

1. **Preview.** The user sends a link. The handler validates it (structure,
   domain allowlist, blocked domains; see [SECURITY.md](../SECURITY.md)),
   checks the preview rate limit, and runs `PreviewDownloadUseCase`, which
   asks the downloader for metadata only (`extract_info(download=False)`).
   The card shows title, author, duration and the format buttons
   `FormatPolicy` allows for this source. The facts the next step needs
   (URL, extractor key, best compatible short side) are stored in Redis
   under a random token (`PreviewContext`, TTL `PREVIEW_CONTEXT_TTL_SECONDS`);
   only the token travels in the callback data.
2. **Request.** A button press resolves the token. `q:` and `back:` read it
   (to redraw the keyboard); `dl:` claims it with `GETDEL`, so a double tap
   cannot start two downloads. `RequestDownloadUseCase` re-validates the
   URL, enforces `FormatPolicy` again (buttons are a hint, the use case is
   the gate), commits a `pending` row and only then enqueues an arq job
   that carries the request id.

`/download <url>` takes the same path without buttons: allowlist, preview,
then `FormatPolicy.default_video_spec`.

The worker's `ProcessDownloadUseCase` claims the row, checks free disk
space, downloads, builds a `DeliverableMedia` and hands it to the notifier,
which picks `send_video`, `send_audio` or `send_document` from the media
facts.

## Process isolation

yt-dlp is synchronous, can hang inside a socket read, and is sometimes
killed by its own dependencies. It never runs on the event loop or in a
thread pool: a thread cannot be killed, and `asyncio.wait_for` only stops
waiting for it.

- **Preview** runs in a `forkserver` child with an overall
  `PREVIEW_TIMEOUT_SECONDS` limit. On expiry the child is terminated, then
  killed. The forkserver preloads the parent's main module once, so each
  child is a cheap fork instead of a fresh interpreter re-importing
  `src.main` (about 2 s). [ADR 0003](adr/0003-preview-timeout-process-isolation.md)
- **Download** runs in a `spawn` child with `DOWNLOAD_TIMEOUT_SECONDS`, the
  same terminate-then-kill shutdown, and results returned over a
  `multiprocessing.Queue` as plain JSON-able facts (path, width, height,
  duration, title, uploader).

Both live in `src/infrastructure/downloader/ytdlp_downloader.py`.

## Progress bridge

Progress crosses three boundaries: the child process, the worker, and the
bot process that owns the user's message.

```
yt-dlp progress_hooks (child)
  -> multiprocessing.Queue
  -> worker drains it on the event loop
  -> ProgressPublisherPort -> Redis PUBLISH umd:progress:<request_id>
  -> bot: TelegramProgressListener PSUBSCRIBE umd:progress:*
  -> ProgressThrottler (>= 3 s and >= 5 points between edits per message)
  -> editMessageText
```

The final phases (`UPLOADING`, `DONE`, `FAILED`) go through the same
channel and bypass the throttle. `download()` waits for the progress queue
to drain before returning, and Redis pub/sub is ordered per channel, so no
event arrives after `DONE`. A failed publish is logged and never fails the
delivery.

## Request status lifecycle

```
pending --claim_for_processing--> processing --mark_done--> done
   |                                   |
   +------------- fail_stale ----------+--------------------> failed
                  (reaper)             +--mark_failed-------> failed
```

- **One transaction per repository call** in the worker and in
  `request_download` (`TransactionalDownloadRequestRepository`). A single
  transaction around a whole job made `processing` invisible to anyone
  else, held a row lock for up to 35 minutes and rolled back to `pending`
  on a crash. Around `request_download` it let the worker see the job
  before the row was committed.
- **Compare-and-set transitions** where a job and the reaper can race:
  `claim_for_processing` is an `UPDATE ... WHERE status IN (pending,
  processing) RETURNING id`; `fail_stale` selects candidates
  `FOR UPDATE SKIP LOCKED` and re-checks the same condition in its
  `UPDATE`.
- **The reaper** is an arq cron (every 5 minutes). A request untouched for
  `job_timeout` (2100 s) plus `STALE_REQUEST_GRACE_SECONDS` is failed and
  its user told so. The `FAILED` commit comes first, the message second:
  exactly-once transition, at-most-once message.
  [ADR 0004](adr/0004-stale-request-reaper.md)

## The database is untrusted input

A row can hold a value this build does not understand (a newer deploy, a
manual edit, a bad migration). Reading it with a bare enum constructor
raises `ValueError` deep inside a job, after the user was told
"accepted".

- Columns with a truthful default degrade to it and log a warning with the
  request id (`MediaType.UNKNOWN`).
- Columns without one (`status`, the `format_kind`/`video_tier` pair)
  raise `CorruptedRecordError`, a domain exception with
  `error_key = "error-internal"`. The worker marks the request failed by id
  and sends a localized message.
- `list_by_user` skips an unreadable row instead of failing the listing.

The CHECK constraints in the schema enforce the same invariants on the
write path; they do not replace the read-path defence.

## Download spec and quality

`DownloadSpec = VideoSpec(VideoTier) | AudioSpec` makes meaningless
combinations unrepresentable (an audio request with a video quality).
[ADR 0001](adr/0001-download-spec-sum-type.md)

- Quality is the **short side** of the frame, not the height: a vertical
  1080x1920 video is "1080p". The download sorts formats with yt-dlp's
  `res:<short side>`.
- The codec Telegram plays inline is one constant, `_COMPATIBLE_VCODEC`
  (h264), read both by the download's format sort and by the preview's
  `max_compatible_short_side`. If the two drifted apart, the buttons would
  offer a 1080p the download cannot pick.
- `FormatPolicy` is a per-extractor kill switch (`DISABLED_FORMATS`),
  applied in the UI and enforced in `RequestDownloadUseCase`.
  [ADR 0002](adr/0002-format-policy-kill-switch.md)

## Large-file delivery

api.telegram.org caps bot uploads at 50 MB; a 720p YouTube video is around
320 MB and 1080p around 730 MB. The bot talks to a local Telegram Bot API
server (`telegram-bot-api` in compose) instead, which raises the cap to
2000 MB. This was chosen over re-encoding to a lower quality (the user
asked for 1080p) and over uploading to object storage and sending a link
(a second system to run, and the file would not play inline).

Files reach the local server as multipart uploads (aiogram's
`FSInputFile`), not by path. A request's download directory is released
when its job ends; the disk guard refuses a download when free space is
below `DOWNLOAD_MIN_FREE_DISK_MB`. [ADR 0005](adr/0005-disk-guard.md)

## Errors and localization

The domain never produces user-facing text. Every downloader error is a
subclass with a semantic `error_key` (`error-private`, `error-geo`,
`error-url-scheme`, ...). The presentation layer resolves it through Fluent
(`locales/{en,ru}/messages.ftl`); the worker resolves it through
`ErrorLocalizerPort` with the user's stored language.

- yt-dlp re-raises everything as `DownloadError`, so
  `infrastructure/downloader/error_classifier.py` classifies by message
  text. The raw message goes to the log and Sentry, never to the user.
- `tests/unit/test_i18n.py` keeps the key sets of both locales identical;
  `tests/unit/test_no_cyrillic_literals.py` fails on Cyrillic in code, so
  text cannot bypass the FTL files.

## Identity

Users are identified by their Telegram id; there is no other login method
yet. `User` has its own id, and `telegram_id` is a nullable attribute of
it, so other login methods (API keys or tokens for a future web or HTTP
client) can be linked to the same user instead of replacing the id.

## Observability

structlog renders every record, including aiogram, arq and SQLAlchemy
logs, as JSON to stdout and to a rotating file per service
(`/var/log/umd/{bot,worker}.log` in the `app_logs` volume). Request id,
extractor and job are bound per task (`bind_log_context`). Sentry is
opt-in (`SENTRY_DSN`): errors only, a fixed low-cardinality tag set, no
frame locals (they hold tokens and URLs).
[ADR 0006](adr/0006-persistent-logs-and-sentry.md)

## Testing strategy

- **Unit tests** cover domain and application against fakes of the ports;
  coverage of those two layers is gated at 90% in CI.
- **Repository and composition tests** run against SQLite (`aiosqlite`).
  Tests about transaction visibility use a file-backed database and read
  through their own connection; `:memory:` shares one connection and hides
  races.
- **Migration tests** run upgrade and downgrade against PostgreSQL in a
  separate CI job, which fails if they are skipped.
- **Live runs in Docker** are required for changes to runtime start-up,
  migrations and extraction: a green unit suite only proves the yt-dlp
  options string, not the file that comes out.

## Engineering pitfalls

Numbered as they were found; code comments refer to them by number. Only
the ones still referenced from the code are listed.

- **Bug #4.** The final file name after an ffmpeg merge or transcode is
  known only in yt-dlp's `post_hooks`, not in the progress hook.
- **Bug #5.** `max_filesize` silently leaves a `.part` file behind; check
  the size before downloading.
- **Bug #6.** Users get short, clean messages chosen by `error_key`;
  diagnostics go to the log. Classified errors are raised without text.
- **Bug #10.** Outside an update context the Fluent core must always be
  called with an explicit locale; there is no aiogram `I18nContext` there.
- **Bug #11.** The i18n core's `startup()` is a coroutine; nothing may use
  the core before it has been awaited.
- **Lesson 11A.1.** Adding a field to the entity and the table is half the
  work: the worker builds value objects from the entity and must pass the
  new field on. Test by capturing the arguments a fake receives, not with a
  bare mock.
- **Lesson 11C.3.** A database row is untrusted input (see above).
- **Lesson 11C.4.** `caplog` sees nothing under structlog; assert on logs
  with `structlog.testing.capture_logs()`.
- **Lesson 23.** Container logs are lost when compose recreates a container;
  hence the persistent log volume.
