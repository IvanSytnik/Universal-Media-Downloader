# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-21

Production hardening, enforced layer boundaries and repository polish.

### Added

- Architecture tests (`tests/unit/test_architecture.py`): every module under `src/` is parsed with `ast`, and the build fails if domain imports anything beyond the standard library, application imports anything beyond domain, or presentation imports infrastructure.
- Composition root (`src/composition.py`): `SqlAlchemyUseCaseProvider` implements the presentation-declared `UseCaseProvider` protocol. Session-scoped use cases are handed out as async context managers, one per unit of work.
- `SetUserLanguageUseCase`, `HealthCheckPort` / `HealthReport` and `PingResultReader` / `PingResult`, so `/language`, `/health` and `/worker_status` go through the application and domain layers.

- MIT `LICENSE`.
- `Makefile` with `help`, `install`, `lint`, `format`, `test`, `test-cov`, `up`, `down`, `logs`, `migrate` targets.
- `.dockerignore`: keeps `.git`, `.venv`, `.env`, tests and caches out of the build context.
- CI coverage gate: `domain` + `application` must stay at or above 90% (branch coverage enabled). `pytest-cov` added to the `dev` extras.
- CI job that builds the Docker image on every push and pull request.
- Worker healthcheck in Compose (`arq --check`), backed by a 60-second arq heartbeat (`health_check_interval`).
- README badges and a sequence diagram of the download lifecycle.

### Changed

- Telegram handlers no longer import infrastructure. They receive `use_cases`, `health_check` and `ping_result_reader` through aiogram workflow data, wired once in `src/main.py`. The `Bot` is built by the composition root instead of the presentation layer.
- Docker image is now multi-stage: dependencies are resolved into a venv in a builder stage, and the runtime image no longer ships `uv`, `curl` or `unzip`.
- Containers run as an unprivileged `app` user (uid 10001) instead of root.
- Deno is copied from the official `denoland/deno` image at a pinned version, replacing `curl … | sh`.
- Postgres and Redis host ports are bound to `127.0.0.1` only, so the default credentials are not reachable from the network.
- Codebase formatted with `ruff format`; CI and `make lint` enforce it with `ruff format --check`.
- CI runs `mypy --strict` explicitly and uses least-privilege `contents: read` permissions with concurrency cancellation.

### Security

- `/health`, `/worker_ping` and `/worker_status` are restricted to Telegram ids listed in the new `ADMIN_TELEGRAM_IDS` setting. The allowlist fails closed (an empty list denies everyone). Non-admin attempts are consumed silently and logged as `admin_command_denied`.
- `/health` no longer echoes raw connection errors (driver messages, hostnames) into the chat. It replies with ✅ / ❌ per component, and diagnostics are logged as `health_check_failed`.

### Removed

- Per-patch working notes `CHANGES.md` and `CHANGES_TESTFIX.md`, superseded by this changelog.

### Upgrade notes

- The containers no longer run as root. A `download_storage` volume created by an older image is owned by root, so the worker cannot write to it. The volume only holds transient downloads, so recreate it: `docker compose down && docker volume rm <project>_download_storage`.

## [0.8.0] - 2026-08-25

### Added

- **Video quality selection (720p / 1080p).** Two-step inline keyboard: after picking video, the preview's buttons are replaced with `[720p] [1080p] [Back]`. MP3 is still downloaded immediately.
- `QualityKind` value object (`hd_720`, `hd_1080`). Its `max_height` is the only place in the codebase that maps a tier to a pixel height.
- `DownloadRequest.quality_kind`, persisted by migration `0004_quality_kind` (`NOT NULL`, server default `hd_720` backfills existing rows).
- Atomic `pop()` on the preview context store (Redis `GETDEL`). Two rapid taps on a confirm button can no longer enqueue two downloads.
- `CorruptedRecordError` domain exception, plus `mark_failed_by_id` on the repository, so a worker can fail a request cleanly even when its row cannot be turned into an entity.
- Tests asserting on failure-path logging. Before this, no test in the project checked log output.

### Changed

- The repository's read path now treats database values as untrusted input. Unknown enum values for `media_type`, `format_kind` and `quality_kind` degrade to a truthful default and log a warning with the request id. An unknown `status` raises `CorruptedRecordError`, because there is no honest fallback for it.
- `list_by_user` skips and logs a corrupt row instead of failing the whole query.
- Callback payloads are `dl:<token>:v720|v1080|a`, `q:<token>` and `back:<token>`. All historical payload forms are still parsed, because inline buttons live in chats indefinitely.
- Expired preview tokens are detected on the `q:` and `back:` steps, not only on the final confirm.
- Hand-written entity fakes in tests were replaced with the real `DownloadRequest`. Fakes remain only for ports.
- The locale parity test reads its key set from the FTL files instead of a hand-maintained list.

### Fixed

- **Every download was 360p.** There were two independent causes: a `yt-dlp` release that predated YouTube's SABR rollout, and a hardcoded `player_client` override that had gone stale. Pinned `yt-dlp>=2026.08.19` and removed the override.
- MP3 downloads fetched the full muxed video stream (~1 GB) only to discard the video. They now prefer an audio-only `m4a` track.
- The video selector requests separate `avc1` video plus `m4a` audio under a height cap, merged to MP4 for inline Telegram playback.

## [0.7.0] - 2026-08-07

### Added

- **Real-time download progress.** The preview message shows percentage, size, speed and ETA, throttled to stay within Telegram's edit rate limits. Updates flow from `yt-dlp` `progress_hooks` through an inter-process queue, an asyncio bridge and Redis pub/sub to a long-lived listener in the bot process.
- "Converting to MP3…" status at the download → post-processing boundary. A minutes-long FFmpeg transcode no longer looks like a hang.
- `ProgressPhase` value object (`downloading` / `converting`), with safe defaults so older events never crash the listener.

### Fixed

- Progress i18n keys were missing from the locale sync-guard test.

## [0.6.0] - 2026-08-02

### Added

- **Format selection.** The preview card offers video (MP4) and audio (MP3 via `FFmpegExtractAudio`).
- `FormatKind` value object, persisted on `DownloadRequest` by migration `0003_format_kind` (server default `video`).

### Fixed

- The MP3 button delivered video. `ProcessDownloadUseCase` built `DownloadOptions` without `format_kind`. Added a regression test that captures the options passed to the downloader.

## [0.5.0] - 2026-07-12

### Added

- **Categorized download errors.** `yt-dlp` failures are classified into seven domain exceptions (private, geo-blocked, age-restricted, unavailable, unsupported media, timeout, too large) plus a fallback. Each carries a semantic `error_key`, never user-facing text.
- Classifier based on message signatures, tested against a corpus of real `yt-dlp` strings.
- `ErrorLocalizerPort` with a Fluent implementation, for the worker path where no update context exists.
- Shared `tests/conftest.py` with `FakeI18n` / `FakeErrorLocalizer` running over the real Fluent core.

### Fixed

- A hardcoded Russian string and a raw exception text leaking to the user on the worker failure path.
- TikTok photo slideshows are reported honestly as unsupported media.
- 21 tests that had drifted from earlier API changes.

## [0.4.0] - 2026-07-08

### Added

- **Internationalization (ru / en).** Every user-facing string lives in Fluent `.ftl` files, with Russian plural forms.
- `/language` command for a manual locale override stored in Redis. Resolution order: override → Telegram `language_code` → `DEFAULT_LOCALE`.
- Migration `0002_user_language`.

## [0.3.0] - 2026-07-07

### Added

- Per-user rate limiting: `RateLimiterPort` with a Redis sliding-window (ZSET) implementation. Defaults are 10 downloads/hour and 5 previews/minute.
- Persistent reply keyboard and bot command menu.
- `/help` generated from settings (platforms from the allowlist, limits from config).

### Fixed

- Large uploads were aborted by aiogram's 60-second default timeout. Added a configurable `FILE_UPLOAD_TIMEOUT_SECONDS`, deliberately without retry, to avoid duplicate deliveries.
- CDN stalls killed downloads. `yt-dlp` now uses socket timeouts, retries and fragment retries. The arq `job_timeout` is set above the download timeout, so the downloader's own timeout always fires first.

## [0.2.0] - 2026-07-05

### Added

- Inline buttons and a guided download flow (aiogram FSM on Redis storage).
- Preview context store: a short-lived token maps to the URL, so callback payloads stay within Telegram's 64-byte limit.
- Configurable domain allowlist with suffix matching, validated before input reaches the application layer.

## [0.1.0] - 2026-07-04

### Added

- Clean Architecture skeleton: domain entities, value objects and ports, with application use cases and infrastructure adapters.
- aiogram 3 bot with `/start`, `/ping` and `/health`.
- PostgreSQL via SQLAlchemy 2 (async) and asyncpg, with Alembic migrations (`0001_initial`) applied on bot startup.
- arq worker on Redis. The bot enqueues and the worker executes, both through the same application layer.
- Media preview via `yt-dlp` `extract_info(download=False)`.
- Real downloads in an isolated OS process, terminated on timeout.
- Optional self-hosted `telegram-bot-api` server sharing a volume with the worker, raising the upload limit from 50 MB to 2000 MB.
- Docker Compose stack with health-checked Postgres and Redis.
- GitHub Actions CI: ruff, mypy, pytest.

[1.0.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.8.0...v1.0.0
[0.8.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/IvanSytnik/Universal-Media-Downloader/releases/tag/v0.1.0
