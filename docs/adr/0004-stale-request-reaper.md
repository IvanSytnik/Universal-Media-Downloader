# ADR 0004: Stale-request reaper with per-call transactions in the worker

- Status: accepted
- Date: 2026-10-26
- Scope: ops minimum before beta, item 2

## Context

A request can stay `pending`/`processing` forever, and its user never
hears back: the worker crashes or is redeployed mid-job, arq cancels a
job at `job_timeout` (the coroutine dies before it can mark anything), or
the queue message is lost. The bot also enqueues the job *before* its
own transaction commits, so a fast worker can find no row, log
`process_download_request_not_found`, and leave the row `pending` once
the bot commits.

Two facts about the code at the time shaped the design:

1. `download_requests` had no time of last change — only `created_at`
   and `completed_at`.
2. `download_job` ran the whole use case inside one `session_scope`: one
   transaction for the entire download, up to `job_timeout` (35 min).
   `processing` was therefore never visible outside the job, the row was
   locked for the whole download (a reaper `UPDATE` would have waited on
   it), a pooled connection sat idle-in-transaction, and a crash rolled
   the row back to `pending` as if the job had never started.

## Decision

1. **`updated_at`** on `download_requests` (migration 0006, backfilled
   with `COALESCE(completed_at, created_at)`, partial index on active
   rows). The repository stamps it on every write, explicitly rather
   than through an ORM `onupdate`, which would skip a re-claim that
   leaves the status unchanged.
2. **One transaction per repository call in the worker**
   (`TransactionalDownloadRequestRepository` / `TransactionalUserRepository`,
   wrapping the session-bound repositories). The worker's writes are
   single-row status transitions with nothing to make atomic together;
   each is now durable and visible as it happens.
3. **Compare-and-set transitions** for the two writes a job and the
   reaper can race on:
   - `claim_for_processing`: `pending|processing → processing` only if
     still active. `ProcessDownloadUseCase` skips the request silently
     when the claim fails: the reaper (or a finished duplicate) already
     closed it and the user has already been told.
   - `fail_stale(updated_before, limit)`: `SELECT … FOR UPDATE SKIP
     LOCKED` (oldest first), then an `UPDATE` that re-checks "active and
     older than the cutoff". Rows a live transaction holds are skipped,
     not waited on; whichever side commits second finds nothing to do.
4. **Threshold** = `JOB_TIMEOUT_SECONDS` (2100, the value arq enforces)
   + `STALE_REQUEST_GRACE_SECONDS` (default 300) → 40 min of silence.
   No live job can be that quiet: the job claims the request at its
   start, and arq kills it at `job_timeout`. The same threshold applies
   to `pending`, measured from creation: 40 minutes in the queue means
   the message is lost or the worker is down, and a queued job that does
   start later fails its claim instead of downloading.
5. **`ReapStaleRequestsUseCase`**, arq cron every 5 minutes, 100 rows
   per tick. The FAILED transition commits first, and only rows it
   actually moved are notified (`error-request-stale`, in the user's
   language). Each row is reaped exactly once and notified at most once.
   A crash between the two steps loses a notification and never sends a
   duplicate. A failed notification is logged and the batch continues.
   Logged per row: `stale_request_reaped request_id user_id
   previous_status error_key`.

## Consequences

- PROCESSING is now visible as it happens: diagnostics and any future
  status UI can rely on it.
- No connection is held for the length of a download. Each job makes a
  handful of short transactions instead of one long one.
- A request that genuinely waits 40+ minutes in a backlog is failed. At
  beta scale that is a symptom, not a load profile; revisit the
  threshold (or measure pending from enqueue) if the queue ever runs
  that deep by design.
- The progress card is not moved to FAILED: its chat/message ids ride
  only in the job payload. The text message is the reliable channel.
- Deploy: stop bot and worker → `alembic upgrade head` → start both. The
  first tick after deploy reaps the rows that are already stuck, and
  their users get the message, possibly about an old request.

## Not done

- Committing the bot's request row *before* enqueueing (the race in
  Context). The reaper now bounds its damage to 40 minutes. The fix
  itself is a separate change to `RequestDownloadUseCase`'s unit of
  work.
- Clock: `updated_at` and the cutoff come from the worker/bot hosts'
  clocks (one host today). On several hosts, use the database's `now()`
  on both sides.
