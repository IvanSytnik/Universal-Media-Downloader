# UMD — File Structure Manifest (актуально на конец Day 7)

> Назначение: новый чат с Claude НЕ требует загрузки всего архива проекта.
> Claude читает этот файл (он в Project Knowledge вместе с HANDOFF), называет
> список нужных файлов, пользователь присылает их содержимое через `cat`:
>
> ```bash
> for f in src/main.py src/config/settings.py; do echo "=== $f ==="; cat "$f"; done
> ```
>
> Полный архив нужен только если патч затрагивает много файлов сразу.

## Корень
- `pyproject.toml` — зависимости, ruff/mypy/pytest конфиг, requires-python 3.13
- `docker-compose.yml` — сервисы: bot, postgres, redis, worker, telegram-bot-api
- `alembic.ini`
- `CHANGES.md` — заметки последнего патча

## src/domain/ (ни от чего не зависит)
- `exceptions.py` — UnsupportedURLError, ExtractionError и др.
- `entities/user.py`, `entities/download_request.py`
- `value_objects/enums.py` — MediaType, DownloadStatus
- `value_objects/media_preview.py` — MediaPreview (frozen dataclass)
- `value_objects/download_options.py` — DownloadOptions
- `value_objects/url_validation.py` — validate_url (структура) + validate_url_against_allowlist (Day 7, суффикс по меткам)
- `interfaces/downloader.py` — DownloaderPort (get_preview, download)
- `interfaces/user_repository.py`, `interfaces/download_request_repository.py`
- `interfaces/task_queue.py` — TaskQueue (enqueue_download)
- `interfaces/storage.py` — StoragePort
- `interfaces/notifier.py` — NotifierPort
- `interfaces/preview_context_store.py` — PreviewContextStorePort (Day 7: save/get/delete token→URL)

## src/application/use_cases/ (зависит только от domain)
- `register_user.py` — RegisterUserUseCase
- `preview_download.py` — PreviewDownloadUseCase(downloader).execute(url) → MediaPreview
- `request_download.py` — RequestDownloadUseCase(user_repo, dl_repo, queue).execute(telegram_id, url) → DownloadRequest
- `process_download.py` — ProcessDownloadUseCase (worker-side: download → storage → notify)
- `trigger_ping_job.py`

## src/infrastructure/
- `database/engine.py` — create_engine, create_session_factory, session_scope
- `database/models.py` — ORM (все datetime — DateTime(timezone=True)!)
- `database/repositories/user_repository.py`, `download_request_repository.py`
- `downloader/ytdlp_downloader.py` — YtDlpDownloader: get_preview (extract_info download=False), download через multiprocessing.Process, post_hooks для финального пути
- `storage/local_storage.py` — LocalFileStorage + TTL cleanup
- `notifier/telegram_notifier.py` — отправка файла пользователю
- `queue/arq_task_queue.py`, `queue/jobs.py`, `queue/worker_settings.py` — arq
- `preview_context/redis_preview_context_store.py` — Day 7: Redis, uuid4.hex токен, SET EX (TTL)
- `telegram/bot_factory.py` — create_telegram_bot (local Bot API server при use_local_bot_api)
- `health.py` — run_health_check

## src/presentation/telegram/
- `bot.py` — create_bot, create_dispatcher(storage) — download_flow_router подключён ПОСЛЕДНИМ
- `keyboards.py` — Day 7: main_menu_keyboard, preview_confirm_keyboard; CB_* константы
- `states.py` — Day 7: DownloadFlow.waiting_for_url
- `formatting.py` — Day 7: format_preview/format_duration (html.escape внутри)
- `handlers/basic.py` — /start (регистрация + кнопки), /ping, /health
- `handlers/preview.py` — /preview <url>
- `handlers/download.py` — /download <url>
- `handlers/download_flow.py` — Day 7: весь guided-флоу (кнопки, FSM, plain-URL, confirm/cancel)
- `handlers/worker.py` — /worker_ping, /worker_status

## src/config/ и src/shared/
- `config/settings.py` — Pydantic Settings: bot_token, postgres_*, redis_*, use_local_bot_api, telegram_api_id/hash, max_deliverable_file_size_mb, allowed_domains (Day 7), preview_context_ttl_seconds (Day 7)
- `shared/logging.py` — structlog (stdlib.LoggerFactory, НЕ PrintLoggerFactory)

## src/main.py
Entrypoint бота: Redis-клиент (общий для RedisStorage FSM и preview_store),
arq pool, DI через dp.start_polling(bot, settings=, session_factory=,
arq_pool=, preview_store=).

## infra/
- `alembic/env.py`, `alembic/versions/0001_initial.py`
- `docker/bot.Dockerfile`, `docker/entrypoint.sh`

## tests/ (105 passed на конец Day 7)
unit: use cases, валидация URL + allowlist, preview context store, download flow
(клавиатуры + предикат URL), форматирование, notifier, downloader (включая
реальный тест kill-механизма процесса), storage, settings, logging, модели.
integration: репозитории (aiosqlite).
