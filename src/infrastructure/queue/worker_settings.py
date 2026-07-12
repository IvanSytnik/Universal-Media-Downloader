"""arq WorkerSettings — run via `arq src.infrastructure.queue.worker_settings.WorkerSettings`.

Day 5 adds real dependencies to `ctx`, created once at startup and torn
down at shutdown — not per-job, since a DB engine / Bot session / process
pool are all expensive to create and safe to share across jobs within
one worker process. Per-job state (the DB *session*, as opposed to the
engine) is still created fresh in each job — see jobs.py::download_job.

Day 10 adds an ``error_localizer`` to ``ctx``: the worker sends localized
failure messages, but has no aiogram ``I18nContext`` (separate process,
no update in flight). It therefore builds the SAME Fluent core the
Telegram side uses and wraps it in ``FluentErrorLocalizer``, which always
resolves keys with an EXPLICIT locale (mandatory outside an update
context — HANDOFF bug #10/#11). ``create_i18n_core().startup()`` is a
COROUTINE and must be awaited before the core is used — done here at
worker startup, mirroring main.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

from src.config.settings import get_settings
from src.infrastructure.database.engine import create_engine, create_session_factory
from src.infrastructure.downloader.ytdlp_downloader import YtDlpDownloader
from src.infrastructure.localization.fluent_error_localizer import FluentErrorLocalizer
from src.infrastructure.notifier.telegram_notifier import TelegramNotifier
from src.infrastructure.queue.jobs import cleanup_expired_downloads_job, download_job, ping_job
from src.infrastructure.storage.local_storage import LocalFileStorage
from src.infrastructure.telegram.bot_factory import create_telegram_bot
from src.presentation.telegram.i18n import DEFAULT_LOCALE, create_i18n_core
from src.shared.logging import configure_logging, get_logger

settings = get_settings()
logger = get_logger(__name__)

# Day 6: this directory is now mounted as a *shared* Docker volume with
# the `telegram-bot-api` service (see docker-compose.yml), not
# container-local anymore. Why: when using a local Bot API server, the
# server process itself reads the file from disk to upload it to
# Telegram — it needs to see the exact same path this worker container
# does. Without the local server, this directory can stay
# container-local (as it did through Day 5); it's the local-server
# feature specifically that requires the shared mount.
DOWNLOAD_STORAGE_DIR = Path("/tmp/umd-downloads")


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(log_level=settings.log_level, environment=settings.environment)
    logger.info(
        "worker_starting",
        environment=settings.environment,
        use_local_bot_api=settings.use_local_bot_api,
    )

    engine = create_engine(settings)
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)

    ctx["downloader"] = YtDlpDownloader()
    ctx["storage"] = LocalFileStorage(base_dir=DOWNLOAD_STORAGE_DIR)
    ctx["max_deliverable_file_size_bytes"] = settings.max_deliverable_file_size_bytes
    ctx["download_timeout_seconds"] = settings.download_timeout_seconds

    # i18n for the worker's failure messages. Build the same Fluent core
    # the Telegram side uses, start it (loads FTL — a COROUTINE, bug #11),
    # then wrap it in the explicit-locale localizer (bug #10).
    i18n_core = create_i18n_core()
    await i18n_core.startup()
    ctx["error_localizer"] = FluentErrorLocalizer(i18n_core, default_locale=DEFAULT_LOCALE)

    notifier_bot = create_telegram_bot(settings)
    ctx["notifier_bot"] = notifier_bot
    ctx["notifier"] = TelegramNotifier(
        notifier_bot,
        max_file_size_bytes=settings.max_deliverable_file_size_bytes,
        file_upload_timeout_seconds=settings.file_upload_timeout_seconds,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker_shutting_down")
    await ctx["notifier_bot"].session.close()
    await ctx["engine"].dispose()


class WorkerSettings:
    functions = [ping_job, download_job]
    cron_jobs = [
        # Every 15 minutes — frequent enough that a 1-hour TTL (see
        # cleanup_expired_downloads_job) never lets much accumulate,
        # infrequent enough not to matter for worker load.
        cron(cleanup_expired_downloads_job, minute={0, 15, 30, 45}),
    ]
    redis_settings = RedisSettings(
        host=settings.redis_host,
        port=settings.redis_port,
        database=settings.redis_db,
    )
    on_startup = startup
    on_shutdown = shutdown
    # Must exceed download_timeout_seconds (1800): the download job's
    # own cooperative timeout in YtDlpDownloader must fire FIRST and
    # kill the child process cleanly, sending the user a proper error.
    # If arq's job_timeout (default 300s!) fired first, it would cancel
    # the coroutine mid-flight with no clean message. +300s margin
    # covers the final upload to Telegram after the download finishes.
    job_timeout = 2100
