# ADR 0006: Persistent JSON logs and opt-in Sentry

- Status: accepted
- Date: 2026-10-26
- Scope: ops minimum before beta, item 4

## Context

Logs went to container stdout only. `docker compose down` or a recreate
discarded them, and with them the diagnostics of whatever failure
prompted the restart (lesson 23). Nothing reported errors on its own:
an unhandled exception in a handler or a job was a line in a log nobody
was reading.

## Decision

1. **Rotating JSON file per service, alongside stdout.** structlog now
   hands events to stdlib unrendered (`ProcessorFormatter`), and each
   handler renders its own way: stdout as before (console locally, JSON
   elsewhere), and a `RotatingFileHandler` at `<LOG_DIR>/<service>.log`
   that is always JSON. Defaults: 50 MB × 10 backups, so at most ~550 MB
   per service. The file is per service (`bot.log`, `worker.log`)
   because rotation is not safe across processes. Rotation is by size,
   not time: disk use is bounded no matter how noisy a day is. Records
   from aiogram, arq and SQLAlchemy go through the same pre-chain and
   land in the file too. If the directory can't be opened, logging
   carries on to stdout and logs `log_file_unavailable`; a bad log
   volume must not stop the bot.
2. **Docker**: a named volume `app_logs` at `/var/log/umd`, with
   `LOG_DIR` set in compose. Not a `./logs` bind mount: the containers
   run as uid 10001, and a fresh named volume inherits the ownership of
   the image's directory. It survives `down` / `up -d`; only `down -v`
   removes it.
3. **One context mechanism**: `bind_log_context(request_id=…,
   extractor_key=…, job=…)` binds structlog contextvars. The worker's
   jobs clear and bind at start. `RequestDownloadUseCase` binds
   `request_id` and `extractor_key`, and `PreviewDownloadUseCase` binds
   `extractor_key`. Each arq job and each aiogram update (polling with
   `handle_as_tasks`) is its own asyncio task, so context stays inside
   the unit of work it belongs to.
4. **Sentry, opt-in on `SENTRY_DSN`** (`sentry-sdk`, inert when unset):
   - Events are ERROR log records (`LoggingIntegration`): our
     `logger.error` calls, and the `exc_info` logs aiogram and arq write
     for unhandled exceptions. Exceptions escaping arq jobs are reported
     by `ArqIntegration`, and the SDK's dedupe drops the duplicate.
     WARNINGs are breadcrumbs: a geo-blocked video is not a bug.
   - `before_send` tags each event with `request_id`, `error_key`,
     `extractor_key`, `job` and `service`. It takes them, in order of
     precedence, from the structured fields of the log record (structlog
     puts the event dict in `record.msg`), from exception attributes
     (`error_key` on every domain error, `request_id` on
     `CorruptedRecordError`), and from the bound context. The message
     becomes the bare event name, so issues group by event, not by the
     ids in a rendered dict. The other fields go to `extra`.
   - `include_local_variables=False`: frame locals hold settings,
     tokens and user URLs. PII collection stays at the SDK default (off).
     `send_default_pii` is not passed: the newest SDKs deprecate it in
     favour of `data_collection`, which the older versions in our pin
     range don't accept. No tracing (`traces_sample_rate=0`).

## Consequences

- Diagnostics outlive containers; `docker compose exec bot tail -f
  /var/log/umd/bot.log` (or `worker.log`) reads them, `jq` filters them.
- With a DSN set, every error arrives with the request id that leads to
  the DB row and to every log line of that job.
- `logger.exception` from structlog code would reach Sentry without a
  stack trace: the traceback is rendered into the event dict, not left
  on the stdlib record. Our code has no such call today; framework
  exceptions (aiogram, arq) are stdlib records and keep their traces.
- Ships nothing to a log aggregator; the files are what one would
  collect (Phase 7).
- The yt-dlp child processes (preview, download) don't configure logging
  or Sentry. Their failures surface as the parent's log lines.
