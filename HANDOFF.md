# UMD — Handoff Document (после Day 7)

> Источник контекста для нового чата. Держать в Project Knowledge вместе с
> PROJECT_SPEC.md и STRUCTURE.md. В новом чате попросить Claude прочитать
> все три файла перед продолжением.

## Что это за проект

**Universal Media Downloader (UMD)** — production-ready Telegram-бот для
скачивания медиа через yt-dlp, ядро будущей SaaS-платформы (Web/API/Mobile —
заложены в архитектуру, НЕ реализованы, по roadmap).

## Текущее состояние: конец Day 7, всё работает end-to-end

Бот качает видео (включая >50 МБ, проверено на 176 МБ) через локальный
Bot API server и присылает в Telegram. Day 7 добавил guided-флоу с кнопками.

## Стек

Python 3.13, aiogram 3, yt-dlp (нативный API), FFmpeg, SQLAlchemy 2 async +
Alembic, PostgreSQL, Redis, arq, Docker Compose, pytest + ruff + mypy strict.
Docker-сервисы: bot, postgres, redis, worker, telegram-bot-api.

## Архитектура

Clean Architecture: domain → application → infrastructure ← presentation.
Полная структура файлов — в STRUCTURE.md (см. ниже "Формат работы").
Спецификация и обоснования — PROJECT_SPEC.md (источник истины).

## Реализовано по дням

| День | Что |
|---|---|
| 1 | Слои, Docker Compose, бот (/start /ping /health), structlog, CI |
| 2 | SQLAlchemy async + Alembic, User/DownloadRequest, RegisterUserUseCase |
| 3 | arq worker (отдельный контейнер), TaskQueue |
| 4 | DownloaderPort + YtDlpDownloader.get_preview, /preview |
| 5 | Реальное скачивание (multiprocessing.Process + terminate по таймауту), LocalFileStorage + TTL, TelegramNotifier, /download |
| 6 | Локальный telegram-bot-api (лимит 50→2000 МБ), лимит размера централизован в Settings (DI) |
| 7 | Inline-кнопки + guided-флоу: /start с кнопками → «пришли ссылку» (FSM waiting_for_url на RedisStorage) ИЛИ голая ссылка сообщением → превью с ✅/❌ → скачивание. PreviewContextStore (Redis, uuid-токен, TTL 600с — обход лимита 64 байта callback_data, защита от дублей и протухших кнопок). Allowlist доменов в Settings (YouTube/youtu.be/TikTok/Instagram/Twitter/X/VK, суффикс по меткам — evilyoutube.com не проходит), проверка на границе Presentation, use cases не тронуты. 105 тестов. |

## Ключевые решения Day 7 (кратко; 1-6 — в PROJECT_SPEC/истории)

- download_flow_router подключается ПОСЛЕДНИМ в Dispatcher — иначе его
  plain-URL хендлер перехватывал бы команды.
- Токен превью удаляется из Redis ДО постановки в очередь — двойной тап ✅
  не создаёт дубль скачивания.
- FSM state очищается ДО обработки присланного текста — пользователь не
  застревает в waiting_for_url при невалидной ссылке.
- Формат превью вынесен в presentation/telegram/formatting.py (нужен двум
  хендлерам, DRY).

## Пойманные баги (НЕ наступать снова)

1. structlog: PrintLoggerFactory несовместим с add_logger_name → stdlib.LoggerFactory.
2. parse_mode=HTML: ЛЮБОЙ внешний текст (title, uploader, текст исключений,
   пользовательский ввод) — только через html.escape().
3. SQLAlchemy: колонки datetime — явно DateTime(timezone=True), иначе asyncpg
   падает на tz-aware datetime.
4. Имя файла после ffmpeg-мёржа — только через post_hooks yt-dlp.
5. max_filesize в yt-dlp молча оставляет .part без исключения — проверять
   размер ДО скачивания через extract_info(download=False).
6. Пользователю — короткие чистые сообщения; диагностика только в лог.

## Формат работы с Claude (ВАЖНО для нового чата)

- **Файлы по запросу вместо архива**: Claude читает STRUCTURE.md, называет
  список нужных файлов, пользователь присылает содержимое:
  `for f in файл1 файл2; do echo "=== $f ==="; cat "$f"; done`
  Полный zip — только если правки затрагивают много файлов.
- **Инкрементальные zip-патчи**: только новые/изменённые файлы + CHANGES.md.
  Пользователь распаковывает `unzip -o` поверх проекта. Мелкие правки
  (1-2 файла) — кодом в чат.
- **Квалити-гейт перед любым патчем**: pytest + ruff check + mypy strict
  в песочнице. Venv пересоздать: `python3 -m venv /home/claude/venv &&
  /home/claude/venv/bin/pip install -e ".[dev]"` — с временным даунгрейдом
  requires-python до 3.12 в pyproject.toml (в песочнице Python 3.12),
  ВЕРНУТЬ 3.13 перед сборкой патча.
- Архитектурные развилки — обсуждать ДО кода (варианты + trade-offs).
- Пользователь общается кратко («делаем» = одобрено, работать автономно).
- Отвечать на русском.

## Day 8 — кандидаты (не начато)

1. **Прогресс скачивания в реальном времени**: progress_hooks yt-dlp →
   межпроцессная очередь → Redis pub/sub → редактирование «⏳»-сообщения.
   Обсуждали концептуально, архитектуру не фиксировали.
2. **Phase 3**: /history (история скачиваний), rate limiting (Redis,
   per user_id), настройки, локализация.

## Не сделано намеренно (YAGNI до своей фазы)

FastAPI/REST, Web/Mobile/Desktop, Premium/Ads/Referral/Payments, выбор
качества/формата перед скачиванием, cookies для приватного контента.
