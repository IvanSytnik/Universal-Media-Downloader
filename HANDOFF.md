# UMD — Handoff Document (после Day 11B.1)

> Источник контекста для нового чата. Держать в Project Knowledge вместе с
> PROJECT_SPEC.md и STRUCTURE.md. В новом чате попросить Claude прочитать
> все три файла перед продолжением.

## Что это за проект

**Universal Media Downloader (UMD)** — production-ready Telegram-бот для
скачивания медиа через yt-dlp, ядро будущей SaaS-платформы (Web/API/Mobile —
заложены в архитектуру, НЕ реализованы, по roadmap).

## Текущее состояние: конец Day 11B.1, всё работает end-to-end

Бот качает видео и mp3 (включая >50 МБ через локальный Bot API server),
показывает прогресс скачивания в реальном времени в том же сообщении, что
и превью, и статус «Конвертирую в MP3…» на границе download→transcode для
audio-пути. 235 тестов зелёные, ruff + mypy --strict чисто.

## Стек

Python 3.13, aiogram 3, aiogram-i18n + Fluent (ru/en), yt-dlp (нативный
API), FFmpeg, SQLAlchemy 2 async + Alembic, PostgreSQL, Redis (FSM +
preview context + rate limit + progress pub/sub), arq, Docker Compose,
pytest + ruff + mypy strict. Docker-сервисы: bot, postgres, redis, worker,
telegram-bot-api.

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
| 7 | Inline-кнопки + guided-флоу: /start с кнопками → «пришли ссылку» (FSM waiting_for_url на RedisStorage) ИЛИ голая ссылка сообщением → превью с ✅/❌ → скачивание. PreviewContextStore (Redis, uuid-токен, TTL 600с). Allowlist доменов. 105 тестов. |
| 8 (+8.1/8.2) | Rate limiting (Redis, per user_id), persistent keyboard, /help; hotfix'ы устойчивости аплоада/скачивания. |
| 9 (i18n) | ru/en локализация через aiogram-i18n + Fluent, ручное переключение языка (/language), User.language в БД (миграция 0002). Explicit-locale паттерн для контекстов без апдейта (бот-хендлеры получают I18nContext автоматически; фоновые задачи — нет, см. баг №10). |
| 10 | Категоризация ошибок yt-dlp в локализованные доменные исключения (`classify_error` → error_key → `ErrorLocalizerPort` → `FluentErrorLocalizer`). Raw-текст только в лог (баг №6), пользователю — короткое локализованное сообщение. |
| 11A | Выбор формата видео/mp3: две кнопки под превью, `FormatKind` (VIDEO/AUDIO) как свойство `DownloadRequest` (домен + БД, миграция 0003), `_build_download_ydl_opts` — audio-ветка `bestaudio/best` + `FFmpegExtractAudio`. |
| 11B | Прогресс скачивания в реальном времени: yt-dlp `progress_hooks` (child-процесс) → `multiprocessing.Queue` → asyncio-bridge → `progress_callback` → `ProgressPublisherPort` → Redis pub/sub (`umd:progress:<request_id>`) → долгоживущий `TelegramProgressListener` в bot-процессе → `editMessageText` с троттлингом (≥3с И ≥5% шаг). |
| 11B.1 | Статус «⏳ Конвертирую в MP3…» на границе download→postprocess (audio-путь только), тем же каналом — yt-dlp's `status=="finished"` перестал откидываться для audio. `ProgressPhase` enum (по прецеденту `FormatKind`). Найдено и НЕ зафикшено в этом патче: audio-путь качает полный muxed-поток (~1 GiB) вместо audio-only дорожки — см. Day 11C ниже. |

## Ключевые решения (кратко; полная история — в CHANGES.md прошлых патчей)

- download_flow_router подключается ПОСЛЕДНИМ в Dispatcher — иначе его
  plain-URL хендлер перехватывал бы команды.
- Токен превью удаляется из Redis ДО постановки в очередь — двойной тап ✅
  не создаёт дубль скачивания.
- FSM state очищается ДО обработки присланного текста — пользователь не
  застревает в waiting_for_url при невалидной ссылке.
- Формат превью вынесен в presentation/telegram/formatting.py (нужен двум
  хендлерам, DRY).
- `format_kind` — свойство домена (что качать, живёт в `DownloadRequest` +
  БД). Координаты прогресс-сообщения (`chat_id`/`message_id`, куда рисовать)
  — деталь доставки, едут в job payload / порт-параметрами, НЕ в домене
  (PROJECT_SPEC §6.1).
- Статус границы фаз («Конвертирую») — тот же Redis-канал, что и обычный
  прогресс, не второй канал; отличается только тем, что listener обходит
  для него троттлинг (одноразовое событие, не поток).

## Пойманные баги (НЕ наступать снова)

1. structlog: PrintLoggerFactory несовместим с add_logger_name → stdlib.LoggerFactory.
2. parse_mode=HTML: ЛЮБОЙ внешний текст (title, uploader, текст исключений,
   пользовательский ввод) — только через html.escape().
3. SQLAlchemy: колонки datetime — явно DateTime(timezone=True), иначе asyncpg
   падает на tz-aware datetime.
4. Имя файла после ffmpeg-мёржа/транскода — только через post_hooks yt-dlp
   (никогда не предсказывать по pre-download info — audio-путь Day 11A
   тоже полагается на это: постпроцессор меняет расширение на .mp3).
5. max_filesize в yt-dlp молча оставляет .part без исключения — проверять
   размер ДО скачивания через extract_info(download=False).
6. Пользователю — короткие чистые сообщения, никогда raw exception text;
   диагностика только в лог.
7-9. (не задокументированы отдельно в этом файле на момент написания —
   см. историю коммитов Day 8-10 при необходимости деталей).
10. Фоновые контексты без aiogram-апдейта (worker, долгоживущий progress
    listener) НЕ имеют `I18nContext` — рендер локализации только через
    явную локаль (`i18n_core.get(key, locale, ...)`), никогда `.get()`
    без локали. Задевает: `FluentErrorLocalizer`, `TelegramProgressListener`.
11. `FluentRuntimeCore().startup()` — корутина, забыть `await` = i18n тихо
    не загружает FTL-файлы.
12. i18n CI-гвард (`tests/unit/test_i18n.py::_REQUIRED_KEYS_SIMPLE` /
    `test_parametrized_keys_resolve`) — новые ключи НЕ подхватываются
    автоматически, несмотря на предположение в TASK_Day11B.md. Ключ, не
    добавленный в этот список вручную, может отсутствовать в одной из
    локалей незамеченным (сам `.ftl`-файл никто не диффит построчно
    между ru/en). Обнаружено на 11B.1: `progress-downloading`/
    `progress-downloading-nostream` (Day 11B) не были добавлены —
    починено вместе с новым `progress-converting`.

## Day 11C (согласовано, не начато) — качество форматов

Найдено на live-прогоне 11B: video-путь всегда отдаёт **360p** (`format
18`), а не «лучшее качество», как предполагал `best[ext=mp4]/best`; и
audio-путь качает **полный muxed video+audio поток** (~1 GiB), а не
отдельную audio-only дорожку, несмотря на корректный `bestaudio/best`
селектор. Сознательно НЕ зафикшено в 11B/11B.1 — отдельный день, не
хвост к прогресс-фиче (нарушило бы «одна фича за раз»).

**Диагностика (сделана, зафиксирована для 11C):**

- `best[ext=mp4]/best` берёт единственный формат с ОДНОВРЕМЕННО
  `vcodec`+`acodec` — а такой формат на практике только один: `18` (360p).
  Все 720p/1080p (`136`/`137`/`398`/`399`/`247`/`248`) — video-only
  (`acodec=none`), нужен `bestvideo[ext=mp4]+bestaudio/best` + merge,
  которого текущий селектор не запрашивает. Нужно перепроверить, почему
  `merge_output_format=mp4` не спасает — сам селектор не просит раздельные
  потоки, мёрж тут ни при чём, проблема в format-строке.
- `player_client=["android","web"]` (текущий, и в `_build_download_ydl_opts`,
  и в `_YDL_OPTS_PREVIEW`) не получает audio-only форматы для проверенного
  видео — SABR-only эксперимент YouTube режет часть форматов у android-
  клиента (warning: "Some android client https formats have been skipped
  as they are missing a URL... SABR-only streaming experiment"). Проверено
  через `yt-dlp -F` с тем же extractor-args: только `18` + storyboard'ы.
  Кандидат `player_client=["android_vr","web"]` отдаёт и audio-only
  (139/249/140/251), и тот же единственный `18` для видео (то есть не
  регрессирует video-путь на проверенном ролике — но это ОДИН ролик,
  не общая гарантия для всех видео/клиентов).

**Продуктовые вопросы для обсуждения ДО кода:**

- Какое качество по умолчанию (720p? 1080p? зависит от размера)?
- Даём ли пользователю выбор качества (третья кнопка/меню) или решаем
  автоматически?
- Как качество соотносится с `max_deliverable_file_size_bytes` (сейчас
  50/2000 МБ) — 1080p на длинном видео легко упрётся в лимит раньше, чем
  360p; нужна ли проверка через `extract_info(download=False)` (как
  сейчас для `max_filesize`, баг №5) до выбора формата?
- `player_client` — общий для preview/video/audio, или разный по
  `format_kind` (audio получает клиент с audio-only, video — клиент с
  лучшим video-качеством, если это окажутся разные наборы)?

**Проверить отдельно:** `deno` (или другой JS-рантайм) в worker-образе —
`docker compose exec worker which deno`. yt-dlp предупреждает про
n-sig decoding без JS-рантайма («some formats may be missing») в
локальном прогоне диагностики (вне контейнера); нужно подтвердить,
установлен ли рантайм именно в `infra/docker/bot.Dockerfile` — если нет,
это отдельная (возможная) причина недостающих форматов, независимая от
`player_client`.

## Формат работы с Claude (ВАЖНО для нового чата)

- **Файлы по запросу вместо архива**: Claude читает STRUCTURE.md, называет
  список нужных файлов, пользователь присылает содержимое, либо (в Claude
  Code) читает файлы из файловой системы напрямую.
- **CHANGES.md — заметка ПОСЛЕДНЕГО патча**, не накопительный лог; полная
  история — HANDOFF.md ("Реализовано по дням") + git log.
- **Квалити-гейт перед любым патчем**: `python -m pytest`, `python -m
  ruff check .`, `python -m mypy --strict src`.
- **Live-прогон обязателен**, когда патч трогает worker/bot startup (урок
  9.1): `docker compose build bot worker && docker compose up -d bot
  worker`, реальное скачивание через настоящего бота — юнит-тесты не
  ловят рантайм-краши инициализации.
- Архитектурные развилки — обсуждать ДО кода (варианты + trade-offs).
- Пользователь общается кратко («делаем» = одобрено, работать автономно
  до следующей развилки/готовности).
- Отвечать на русском.

## Не сделано намеренно (YAGNI до своей фазы)

FastAPI/REST, Web/Mobile/Desktop, Premium/Ads/Referral/Payments, /history,
Prometheus-метрики, cookies для приватного контента, выбор качества видео
(см. Day 11C выше — согласовано отдельным днём, не «никогда»).
