# UMD — File Structure Manifest (актуально на конец Day 11B.1)

> Назначение: новый чат с Claude НЕ требует загрузки всего архива проекта.
> Claude читает этот файл (он в Project Knowledge вместе с HANDOFF), называет
> список нужных файлов, пользователь присылает их содержимое через `cat`
> (или Claude Code читает их напрямую из файловой системы):
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
- `CHANGES.md` — заметка ПОСЛЕДНЕГО патча (не накопительная)
- `HANDOFF.md` — накопительная история по дням, пойманные баги, план
- `locales/{ru,en}/messages.ftl` — Fluent-переводы (Day 9), структурно синхронны

## src/domain/ (ни от чего не зависит)
- `exceptions.py` — UnsupportedURLError, ExtractionError, категоризированные
  доменные ошибки (Day 10: PrivateVideoError, GeoBlockedError,
  AgeRestrictedError, UnavailableError, DownloadTimeoutError, FileTooLargeError
  и др. — каждая с `error_key` для локализации)
- `entities/user.py` — `+ language` (Day 9)
- `entities/download_request.py` — `+ format_kind` (Day 11A)
- `value_objects/enums.py` — MediaType, DownloadStatus
- `value_objects/media_preview.py` — MediaPreview (frozen dataclass)
- `value_objects/download_options.py` — DownloadOptions (`+ format_kind`, Day 11A)
- `value_objects/download_progress.py` — DownloadProgress (Day 11B; `+ phase:
  ProgressPhase = DOWNLOADING`, Day 11B.1)
- `value_objects/progress_phase.py` — **Day 11B.1**: `ProgressPhase(StrEnum)`
  — DOWNLOADING/CONVERTING, дефолт-безопасный (прецедент FormatKind)
- `value_objects/format_kind.py` — **Day 11A**: `FormatKind(StrEnum)` —
  VIDEO/AUDIO (что ЗАПРОСИЛ пользователь, отдельно от MediaType — чем
  ЯВЛЯЕТСЯ источник)
- `value_objects/url_validation.py` — validate_url (структура) +
  validate_url_against_allowlist (Day 7, суффикс по меткам)
- `interfaces/downloader.py` — DownloaderPort (get_preview, download —
  `progress_callback` опционален, Day 11B)
- `interfaces/user_repository.py`, `interfaces/download_request_repository.py`
- `interfaces/task_queue.py` — TaskQueue (enqueue_download — `+ chat_id`/
  `message_id` параметры, Day 11B)
- `interfaces/storage.py` — StoragePort
- `interfaces/notifier.py` — NotifierPort
- `interfaces/preview_context_store.py` — PreviewContextStorePort (Day 7)
- `interfaces/error_localizer.py` — **Day 10**: ErrorLocalizerPort
  (error_key + locale → строка; explicit-locale, баг №10)
- `interfaces/rate_limiter.py` — **Day 8**: RateLimiterPort
- `interfaces/progress_publisher.py` — **Day 11B**: ProgressPublisherPort
  (publish(request_id, chat_id, message_id, language, DownloadProgress))

## src/application/use_cases/ (зависит только от domain)
- `register_user.py` — RegisterUserUseCase
- `preview_download.py` — PreviewDownloadUseCase(downloader).execute(url) → MediaPreview
- `request_download.py` — RequestDownloadUseCase — `+ format_kind` (Day 11A)
- `process_download.py` — ProcessDownloadUseCase (worker-side: download →
  storage → notify). Day 10: категоризированные ошибки → ErrorLocalizerPort.
  Day 11B: `execute(request_id, chat_id, message_id)`, строит
  `progress_callback` → `ProgressPublisherPort.publish` (прозрачно форвардит
  и converting-снапшоты, Day 11B.1 — без изменений кода)
- `trigger_ping_job.py`

## src/infrastructure/
- `database/engine.py` — create_engine, create_session_factory, session_scope
- `database/models.py` — ORM (все datetime — DateTime(timezone=True)!);
  `+ language` (Day 9), `+ format_kind` (Day 11A)
- `database/repositories/user_repository.py`, `download_request_repository.py`
- `downloader/ytdlp_downloader.py` — YtDlpDownloader: get_preview, download
  через multiprocessing.Process, post_hooks для финального пути (баг №4).
  Day 11A: `_build_download_ydl_opts` (video/audio ветки). Day 11B: progress
  bridge (child → `multiprocessing.Queue` → executor thread → asyncio
  `bridge` → `progress_callback`), `_build_download_progress`. Day 11B.1:
  `_translate_progress_status` (чистая функция, вынесена из
  `_record_progress` ради юнит-тестируемости) — audio-only «finished» →
  `phase=CONVERTING` маркер, video не эмитит.
- `downloader/error_classifier.py` — **Day 10**: raw yt-dlp message →
  категория (`classify_error`)
- `storage/local_storage.py` — LocalFileStorage + TTL cleanup
- `notifier/telegram_notifier.py` — отправка файла пользователю
- `queue/arq_task_queue.py`, `queue/jobs.py`, `queue/worker_settings.py` —
  arq. Day 11B: `download_job` несёт `chat_id`/`message_id` (обязательные —
  несовместимо со старым payload, см. CHANGES.md → «Перед деплоем»);
  `worker_settings.py` поднимает `error_localizer`/`progress_publisher` в
  DI-контексте воркера (баг №11 — `i18n_core.startup()` это корутина)
- `preview_context/redis_preview_context_store.py` — Day 7
- `rate_limit/redis_rate_limiter.py` — **Day 8**
- `localization/fluent_error_localizer.py` — **Day 10**: FluentErrorLocalizer
  (explicit-locale, баг №10); строит core через тот же `create_i18n_core`,
  что и bot-процесс, см. `presentation/telegram/i18n.py`
- `progress/redis_progress_publisher.py` — **Day 11B**:
  RedisProgressPublisher — один JSON-payload на `umd:progress:<request_id>`
  (percent/downloaded_bytes/total_bytes/speed/eta/phase + chat_id/
  message_id/language); StrEnum `phase` сериализуется как строка
  автоматически (Day 11B.1)
- `telegram/bot_factory.py` — create_telegram_bot (local Bot API server при
  use_local_bot_api)
- `health.py` — run_health_check

## src/presentation/telegram/
- `bot.py` — create_bot, create_dispatcher(storage) — download_flow_router
  подключён ПОСЛЕДНИМ
- `i18n.py` — **Day 9**: `create_i18n_core`, `SUPPORTED_LOCALES`,
  `DEFAULT_LOCALE`, `collect_button_translations`
- `keyboards.py` — Day 7 + Day 8 (persistent keyboard) + Day 11A (две
  кнопки формата: `btn-confirm-video`/`btn-confirm-audio`,
  `confirm_callback_data`/`parse_confirm_callback` с суффиксом формата,
  терпит legacy bare-форму)
- `states.py` — Day 7: DownloadFlow.waiting_for_url
- `formatting.py` — Day 7: format_preview/format_duration (html.escape внутри)
- `progress_listener.py` — **Day 11B**: `TelegramProgressListener`
  (долгоживущий PSUBSCRIBE `umd:progress:*` в bot-процессе, рядом с
  `dp.start_polling()`, explicit-locale — баг №10), `ProgressThrottler`
  (чистая debounce-логика: ≥3с И ≥5% шаг). Day 11B.1: converting-фаза
  обходит троттлинг целиком, рендерит `progress-converting`.
- `handlers/basic.py` — /start (регистрация + кнопки), /ping, /health, /help (Day 8)
- `handlers/preview.py` — /preview <url>
- `handlers/download.py` — /download <url> — `+ format_kind` (Day 11A)
- `handlers/download_flow.py` — весь guided-флоу (кнопки, FSM, plain-URL,
  confirm/cancel); Day 11A: парсит формат из callback; Day 11B: передаёт
  `chat_id`/`message_id` превью-сообщения в job для последующего
  редактирования прогрессом
- `handlers/worker.py` — /worker_ping, /worker_status
- `handlers/language.py` — **Day 9**: /language — ручное переключение,
  пишет `User.language`

## src/config/ и src/shared/
- `config/settings.py` — Pydantic Settings: bot_token, postgres_*, redis_*,
  use_local_bot_api, telegram_api_id/hash, max_deliverable_file_size_mb,
  allowed_domains (Day 7), preview_context_ttl_seconds (Day 7),
  rate-limit настройки (Day 8)
- `shared/logging.py` — structlog (stdlib.LoggerFactory, НЕ PrintLoggerFactory)

## src/main.py
Entrypoint бота: Redis-клиент (общий для RedisStorage FSM, preview_store,
rate limiter, progress pub/sub), arq pool, i18n_core startup, DI через
`dp.start_polling(...)`. Day 11B: поднимает `TelegramProgressListener` как
отдельную asyncio-задачу рядом с polling (explicit-locale, баг №10).

## infra/
- `alembic/env.py`, `alembic/script.py.mako`
- `alembic/versions/0001_initial.py`
- `alembic/versions/0002_user_language.py` — **Day 9**
- `alembic/versions/0003_format_kind.py` — **Day 11A** (server_default
  `'video'`, backfill существующих строк)
- `docker/bot.Dockerfile`, `docker/entrypoint.sh` — общий образ для bot и
  worker (entrypoint с миграциями только у bot, см. docker-compose.yml)

## tests/ (235 passed на конец Day 11B.1)
49 файлов. unit: use cases, валидация URL + allowlist, preview context
store, download flow (клавиатуры + предикат URL), форматирование,
notifier, downloader (включая реальный тест kill-механизма процесса и
`_translate_progress_status`/`_build_download_progress`), storage,
settings, logging, модели, rate limiter, i18n (ru/en resolve + CI-гвард
на ключи, баг №12), error classifier/localizer, progress publisher/
listener/throttler/value-object (Day 11B/11B.1). integration: репозитории
(aiosqlite).
