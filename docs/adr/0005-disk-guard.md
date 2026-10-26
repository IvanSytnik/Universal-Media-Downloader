# ADR 0005: Disk guard for the download directory

- Status: accepted
- Date: 2026-10-26
- Scope: ops minimum before beta, item 3

## Context

Downloads land in `/tmp/umd-downloads/<request_id>/`, on a Docker volume
shared with the local Bot API server. A 1080p video is ~726 MB, and a
video+audio download briefly holds both streams plus the merged file.
What the code did:

- **Nothing removed a request's directory when its job ended.** A
  delivered file stayed until the cron's 1 h TTL, so on a normal day
  most of the disk usage was finished downloads, not crash leftovers.
- The cron measured age by the **directory's** mtime. That changes only
  when entries are added, removed or renamed. A `.part` that keeps
  growing does not move it, so the directory looks idle. Only "TTL >
  job length" kept a live download from being deleted.
- `rmtree(ignore_errors=True)` counted a failed removal as a success.
- Nothing checked free space before starting a download.

## Decision

Three layers, ordered by how much disk each one actually reclaims:

1. **`StoragePort.release(request_id)`**, called by
   `ProcessDownloadUseCase` in a `finally` once the request is claimed.
   It runs on every outcome: delivered, failed, refused, or an
   unexpected exception. Never on an unclaimed request: its directory
   may belong to the job that does own it. Never raises; a failure is
   logged (`storage_release_incomplete`) and left to the cron.
2. **Admission control**: before downloading, `available_bytes()` is
   compared with `DOWNLOAD_MIN_FREE_DISK_MB` (default 3072, `0`
   disables). Below the floor the request fails with
   `InsufficientStorageError` (`error-storage-full`, "try again in a few
   minutes") and yt-dlp never starts. Otherwise a download that fills
   the disk breaks every download running next to it. We refuse rather
   than evict: the only evictable data is the files of live downloads.
3. **Cron sweep of crash leftovers** (every 15 min). Age is the newest
   `lstat` mtime anywhere in the entry, without following symlinks. The
   threshold is the reaper's, `job_timeout + STALE_REQUEST_GRACE_SECONDS`
   (40 min): a live job writes to its files more often than that, and arq
   kills any job older than `job_timeout`. Stray top-level files are
   swept too. Only entries that are really gone afterwards are counted.
   Each failing path is logged (`storage_remove_failed`). The cron also
   logs `storage_low_disk_space` when free space is under the floor.
   That is the signal an operator sees.

Open ("locked") files are not special on Linux: unlinking one is legal,
and the space returns when the last handle closes. The real danger is
deleting a live download, and layer 3's activity age guards against it.

All filesystem work runs in `asyncio.to_thread`: the worker's event loop
also drives progress updates.

## Consequences

- Disk usage is bounded by what is in flight, not by the last hour of
  traffic.
- Under disk pressure users get an honest "overloaded, retry" instead
  of a download that fails halfway.
- The floor is static. The right value is roughly
  `2 × max file size × concurrent jobs`, and that is the operator's call
  (documented in `.env.example`). There are no per-job space
  reservations.
- The local Bot API server's own working directory
  (`/var/lib/telegram-bot-api`) is not covered. It is a separate volume
  with its own cache.
