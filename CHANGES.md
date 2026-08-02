# Day 11A — Выбор формата: видео / mp3

Инкрементальный патч. Распаковать `unzip -o` поверх корня проекта.

## Что сделано

Под превью теперь **две кнопки подтверждения** вместо одной: «⬇️ Видео» и
«🎵 MP3». Пользователь выбирает, что скачать — исходное видео или только
аудиодорожку, извлечённую в mp3 (транскод системным ffmpeg). Выбор
доезжает до воркера через БД (поле запроса), а не через payload очереди —
воркер, как и раньше, восстанавливает весь запрос из базы по id.

Это первая половина Day 11. Вторая (11B) — прогресс скачивания в
реальном времени — отдельным патчем, т.к. трогает рантайм-инициализацию
(worker/bot startup) и требует live-прогона.

## Архитектурное решение (зафиксировано до кода)

**`format_kind` — свойство запроса, живёт в домене и в БД.** Это то,
ЧТО качать — атрибут `DownloadRequest`, а не деталь транспорта. Поэтому:
поле сущности → колонка → миграция → маппинг в репозитории. Контраст с
11B, где координаты «⏳»-сообщения (КУДА рисовать прогресс) — деталь
доставки и поедут в payload задачи, не в домене. Разделение по
Dependency Rule (PROJECT_SPEC §6.1): Telegram-специфика не течёт в домен.

**Аудио = mp3 через `FFmpegExtractAudio`.** Предсказуемый универсальный
контейнер, ffmpeg уже обязателен (PROJECT_SPEC §2). Финальное имя файла —
по-прежнему из `post_hooks` (баг №4): постпроцессор меняет расширение на
.mp3, post_hooks отдаёт реальный путь после транскода — предсказание не
нужно, mp3-путь покрыт тем же механизмом, что и video-мёрж.

## Новые файлы

- `src/domain/value_objects/format_kind.py` — `FormatKind` (VIDEO/AUDIO).
  Отдельно от `MediaType`: `MediaType` — чем ЯВЛЯЕТСЯ источник, `FormatKind`
  — что ЗАПРОСИЛ пользователь. Одно видео можно скачать и как video, и как
  mp3 — это разные намерения, значит разные концепты.
- `infra/alembic/versions/0003_download_request_format_kind.py` — колонка
  `download_requests.format_kind` String(20), NOT NULL, server_default
  `'video'` (существующие строки backfill'ятся в video без отдельного
  data-шага — как вводился media_type). **Проверь `down_revision`:**
  указан `"0002_user_language"` — если фактический revision id в твоём
  0002-файле другой, поправь одну строку.
- `tests/unit/test_confirm_callback.py` — encode/decode callback, legacy
  bare-форма, неизвестный код → video, бюджет 64 байта, сохранение
  префикса `dl:` для роутера.
- `tests/unit/test_download_ydl_opts.py` — video/audio ветки ydl_opts,
  инвариант «общие опции надёжности идентичны в обоих форматах»,
  max_filesize backstop.
- `tests/unit/test_request_download_format.py` — проброс format_kind в
  use case (дефолт video / явный audio), дефолт на уровне сущности.
- `tests/unit/test_ytdlp_downloader.py` — **починка тестового долга.**
  `_run_download_in_process` получил 5-й позиционный аргумент
  (`format_kind_value`), а 4 существующих теста мокали её сигнатурой на
  4 аргумента → `TypeError: takes 4 positional arguments but 5 were
  given`. Четыре мока (1 lambda + 3 def) обновлены: принимают
  `format_kind_value` и игнорируют его. Логика/ассерты не тронуты —
  тесты проверяют маппинг исключений `download()`, который от формата не
  зависит. Файл включён в патч целиком, чтобы zip был самодостаточным.

## Изменённые файлы

- `src/domain/value_objects/download_options.py` — `+ format_kind:
  FormatKind = VIDEO` (opt-in, обратная совместимость).
- `src/domain/entities/download_request.py` — `+ format_kind` поле и
  аргумент `create(..., format_kind=VIDEO)`.
- `src/infrastructure/database/models.py` — колонка `format_kind`
  (server_default "video").
- `src/infrastructure/database/repositories/download_request_repository.py`
  — маппинг `format_kind` в `_to_entity` и `create`. В `update` НЕ
  трогается: формат неизменяем после создания.
- `src/application/use_cases/request_download.py` — `execute(telegram_id,
  url, format_kind=VIDEO)`; кладёт формат в сущность.
- `src/infrastructure/downloader/ytdlp_downloader.py` — новый
  `_build_download_ydl_opts(...)` (единая сборка opts, format-специфичные
  ключи слоями поверх общих); `format_kind` проброшен через
  `download → _run_download_in_process → _download_worker_entrypoint` как
  строковое значение (spawn/pickle-безопасно) и реконструирован в enum в
  child. Video-ветка байт-в-байт прежняя.
- `src/presentation/telegram/keyboards.py` — `preview_confirm_keyboard`
  рисует две кнопки формата + отмену; `confirm_callback_data(token, fmt)`
  и `parse_confirm_callback(data)` — encode/decode с суффиксом формата
  (`dl:<token>:v|a`), терпит legacy `dl:<token>`.
- `src/presentation/telegram/handlers/download_flow.py` —
  `handle_confirm_download` парсит формат из callback, передаёт в use
  case; лог `format_kind`. Роутер по-прежнему `startswith("dl:")` —
  ловит обе кнопки.
- `locales/{ru,en}/messages.ftl` — `+ btn-confirm-video`,
  `+ btn-confirm-audio`; `help-text` шаг 3 обновлён под две кнопки.
  `btn-confirm` оставлен (на случай ссылок), локали структурно синхронны.

## Проверено (в песочнице Claude, Python 3.12)

- `parse_confirm_callback` / `confirm_callback_data`: roundtrip
  video+audio, legacy bare-форма → video, неизвестный код → video,
  callback 37 байт (лимит 64), префикс `dl:` сохранён.
- `_build_download_ydl_opts`: video = `best[ext=mp4]/best` + mp4-merge,
  audio = `bestaudio/best` + FFmpegExtractAudio mp3; общие опции
  надёжности идентичны; max_filesize backstop на обоих путях.
- Проброс format_kind через `RequestDownloadUseCase` (дефолт video /
  явный audio), дефолт на уровне сущности.
- Починенный `test_ytdlp_downloader.py`: 4 ранее падавших теста
  (`TypeError` от нового 5-го аргумента) зелёные, 7 прежних не задеты.
- 25 тестов зелёные (14 новых + 11 в починенном ytdlp_downloader);
  `ruff check` чисто; все файлы патча компилируются.

## ⚠️ Прогнать локально перед коммитом (среда 3.13)

1. **Полный `pytest`** — на реальном коде (3.13) должен быть полностью
   зелёным: первый прогон 11A дал 4 падения в `test_ytdlp_downloader.py`
   (`TypeError` от нового 5-го аргумента `_run_download_in_process`) —
   **исправлено в этом же патче** (см. выше), теперь 195/195 ожидаемо
   зелёные. В песочнице Claude — 3.12 + faithful-стабы части closure, на
   реальном коде прогнать весь набор для подтверждения.
2. **`mypy --strict src`** — в песочнице не гонялся (нет полного
   окружения типов). Ожидаемо чисто: новые сигнатуры полностью
   типизированы, `FormatKind` — StrEnum.
3. **Миграция:** `alembic upgrade head` на чистой БД и поверх
   существующей (проверить backfill server_default). Сверить
   `down_revision` с фактическим revision id файла 0002.
4. Быстрый живой прогон: превью → «🎵 MP3» → приходит mp3; превью →
   «⬇️ Видео» → приходит mp4 (регресс video-пути).

## Не входит в 11A (следующий патч 11B)

Прогресс скачивания в реальном времени (progress_hooks → mp-очередь →
Redis pub/sub → editMessageText с троттлингом). Трогает startup —
обязателен live-прогон (урок 9.1).
