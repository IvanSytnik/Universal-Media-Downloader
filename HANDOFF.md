# UMD — Handoff Document (после Day 11C: выбор качества 720/1080 закрыт целиком)

> Источник контекста для нового чата. Держать в Project Knowledge вместе с
> PROJECT_SPEC.md и STRUCTURE.md. В новом чате попросить Claude прочитать
> все три файла перед продолжением.
> ИСТОЧНИК ИСТИНЫ — PROJECT_SPEC.md (v2, деление по слоям).
> ⚠️ PROJECT_SPEC.md живёт ТОЛЬКО в Project Knowledge, его НЕТ в git-репо —
> Claude Code его не видит и восстанавливает дисциплину по этому HANDOFF.
> Стоит положить PROJECT_SPEC.md в корень репозитория.

## Что это за проект

**Universal Media Downloader (UMD)** — production-ready Telegram-бот для
скачивания медиа через yt-dlp, ядро будущей SaaS-платформы (Web/API/Mobile —
заложены в архитектуру, НЕ реализованы, по roadmap).

## Текущее состояние: Day 11C закрыт ПОЛНОСТЬЮ, всё работает end-to-end

Бот качает видео в качестве, которое ВЫБРАЛ пользователь (720p/1080p,
двухшаговые кнопки), включая >700 МБ через локальный Bot API server, шлёт
в Telegram, две локали (ru/en), классифицированные ошибки, прогресс в
реальном времени, выбор video/mp3. 314 тестов зелёные, ruff + mypy strict
чистые. Живой прогон полного флоу через бота пройден.

## Стек

Python 3.13, aiogram 3, aiogram-i18n + fluent.runtime, yt-dlp
(нативный API, **пин >=2026.08.19**), FFmpeg, SQLAlchemy 2 async + Alembic,
PostgreSQL, Redis, arq, Docker Compose, deno (в образе, для yt-dlp-ejs),
pytest + ruff + mypy strict.
Docker-сервисы: bot, postgres, redis, worker, telegram-bot-api.

## Архитектура

Clean Architecture: domain → application → infrastructure ← presentation.
Полная структура файлов — в STRUCTURE.md. Спецификация — PROJECT_SPEC.md.

## Реализовано по дням

| День | Что |
|---|---|
| 1 | Слои, Docker Compose, бот (/start /ping /health), structlog, CI |
| 2 | SQLAlchemy async + Alembic, User/DownloadRequest, RegisterUserUseCase |
| 3 | arq worker (отдельный контейнер), TaskQueue |
| 4 | DownloaderPort + YtDlpDownloader.get_preview, /preview |
| 5 | Реальное скачивание (multiprocessing.Process + terminate по таймауту), LocalFileStorage + TTL, TelegramNotifier, /download |
| 6 | Локальный telegram-bot-api (лимит 50→2000 МБ), лимит размера в Settings (DI) |
| 7 | Inline-кнопки + guided-флоу (FSM на RedisStorage), PreviewContextStore, allowlist доменов |
| 8 | Rate limiting (RedisRateLimiter, sliding window ZSET); persistent ReplyKeyboardMarkup; menu-кнопка; /help из Settings. Хотфиксы 8.1 (upload timeout), 8.2 (yt-dlp retries/socket_timeout). |
| 9 | i18n (ru/en): aiogram-i18n + Fluent. User.language (миграция 0002). Приоритет локали: override(Redis)→language_code→en. Хотфикс 9.1 (i18n get без локали на старте). |
| 10 | Категоризация ошибок yt-dlp: 7 доменных категорий + fallback, error_key. Локализованные сообщения в ОБОИХ путях (preview + worker через ErrorLocalizerPort). 181 тест. |
| 11A | Выбор формата видео/mp3. Две кнопки. format_kind: свойство запроса (сущность + БД, миграция 0003). Callback dl:<token>:v\|a. Audio = bestaudio + FFmpegExtractAudio mp3. Хотфиксы 11A.0 (длинный revision id > VARCHAR(32)), 11A.1 (worker не прокидывал format_kind → mp3 слал видео). 197 тестов. |
| 11B | Прогресс скачивания в реальном времени: progress_hooks → multiprocessing.Queue → Redis pub/sub → throttled editMessageText. ProgressPhase StrEnum. Статус «Конвертирую в MP3» на границе фаз. Коммит 6ebc6fa. 241 тест. |
| 11C.1 | **Реальное качество вместо 360p.** Пин yt-dlp>=2026.08.19 (чинит SABR: 360p+403). Убран хардкод player_client android/web — он сам был причиной 360p. Новый video-селектор bestvideo[height<=N][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a] + mp4-merge. Audio bestaudio[ext=m4a]/... — чинит combined-1ГБ. Параметр max_height (дефолт константа 720). Live: 720p=321МБ, 1080p=726МБ, mp3=64МБ. 241 тест (+6). |
| 11C.2 | QualityKind (HD_720/HD_1080), `max_height` — единственный маппинг тир→высота. Поле на сущности + миграция 0004 (String(16), NOT NULL, server_default 'hd_720'). Живой upgrade: 43 старые строки забэкфилились, downgrade -1 проверен. 256 тестов. |
| 11C.3 | **Вне плана, найдено при ревью.** Чтение из БД — недоверенный вход: голый конструктор enum давал ValueError из get_by_id уже ПОСЛЕ «принято». Деградация с логом для колонок с честным дефолтом, CorruptedRecordError (error_key=error-internal) для status. Воркер помечает failed by id и шлёт локализованное сообщение. 271 тест. |
| 11C.4 | Цепочка запись→чтение: use case → сущность → БД → воркер → DownloadOptions → селектор. argument-capture тесты на ОБА тира (урок 11A.1). `_DEFAULT_MAX_HEIGHT` стал производной от QualityKind. Live: ffprobe 1280x720 и 1920x1080. 285 тестов. |
| 11C.5 | Двухшаговый UI (раскладка B): [Видео][MP3] → [720p][1080p][Назад]. Callback dl:<token>:v720\|v1080 (41 байт), q:, back:. Атомарный pop() (Redis GETDEL) — защита от двойного тапа. Live через бота. 299 тестов. |
| 11C.6 | Закрыты долги: list_by_user пропускает битую строку вместо падения; тест паритета локалей читает ключи из FTL, а не из ручного списка; логирование путей отказа покрыто тестами (раньше ассертов на логи не было нигде). 314 тестов. |

## Day 11C — ЗАКРЫТ ЦЕЛИКОМ (фича «выбор качества 720/1080»)

Все пять этапов сделаны, плюс один незапланированный (харденинг чтения
БД) и четыре закрытых долга. Детали по каждому — в CHANGES.md, разбивка
по коммитам — в таблице дней выше. Здесь остаётся только то, что нужно
знать ДАЛЬШЕ.

**Итоговый UX:**
```
Превью → [⬇️ Видео] [🎵 MP3]
   MP3 → сразу скачивание (качество неприменимо)
   Видео → editMessageReplyMarkup → [720p] [1080p] [◀️ Назад]
```
Callback-бюджет: `dl:`(3)+hex32+`:v1080`(6)=41 < 64. `q:<token>`=34,
`back:<token>`=37. Audio игнорирует quality_kind (в БД пишется дефолт,
никто его не читает).

**Инварианты, которые нельзя ломать:**
- `QualityKind.max_height` — ЕДИНСТВЕННЫЙ маппинг «тир → высота».
  Заводить словарь в инфраструктуре нельзя; `_DEFAULT_MAX_HEIGHT` —
  производная от него, а не литерал.
- Новый тир добавляется в enum + один ключ подписи; клавиатура и коды
  callback'ов строятся итерацией по `QualityKind`.
- Токен превью ЧИТАЕТСЯ на шагах `q:`/`back:` и ЗАБИРАЕТСЯ (`pop`,
  атомарно) только на `dl:`. Вернуть get+delete = вернуть двойные
  скачивания по двойному тапу.
- Любой новый callback-префикс не должен быть префиксом существующего —
  есть тест, но думать об этом надо при вводе.

**Что осталось незакрытым по фиче:** тиры выше 1080p, запоминание выбора
per-user, история скачиваний (данные копятся — format_kind и quality_kind
уже в БД).

## ⚠️ ОБЯЗАТЕЛЬНО перед продовым деплоем (напоминания)

1. **`MAX_DELIVERABLE_FILE_SIZE_MB`** должен быть поднят (1080p ~726 МБ).
   На чистом деплое `.env` собирается заново; дефолт 50 → 1080p/720p не
   доставятся (error-too-large при успешном скачивании). Занести в
   DEPLOYMENT.
2. **Осушить очередь arq** перед деплоем 11B (старый payload несовместим с
   сигнатурой `download_job(ctx, request_id, chat_id, message_id)`).
3. **yt-dlp пин** — не откатывать ниже 2026.08.19, иначе вернётся 360p+403.

## ⚠️ ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ (не баг, Day 9)

Синее меню команд Telegram НЕ слушается /language (рендерится клиентом по
локали приложения). Косметическое, структурно неустранимо.

## Фото/карусели — ДИАГНОСТИРОВАНО и ОТЛОЖЕНО (не строим)

Живая диагностика доказала: **yt-dlp не извлекает ФОТО из
Instagram-каруселей** на нашем стеке — фото-слайды падают с `No video
formats found` (info-dict не создаётся, поэтому даже `--write-thumbnail`
до них не дотягивается), cookies не помогают, качаются только видео-слайды
(3 из 20 в тесте). TikTok `/photo/` → `Unsupported URL` (экстрактор
отказывается). Центральная посылка брифа («yt-dlp отдаёт карусель как N
медиа») для фото ЛОЖНА на обеих площадках. Конкуренты используют не-yt-dlp
инструменты (gallery-dl/instaloader/GraphQL).

**Решение:** Variant A = «только видео-карусели» (доставка нескольких
видео альбомом) отложен; полноценные фото = Variant B (отдельный
gallery-dl адаптер за DownloaderPort) — отдельный крупный этап, если фото
станут приоритетом. Полная архитектура (единый DownloadResult.items,
sendMediaGroup батчи ≤10, обязательный частичный успех, mixed-типы) уже
спроектирована — в `TASK_photo_carousel.md`.

## Пойманные баги (НЕ наступать снова)

1. structlog: PrintLoggerFactory ✗ add_logger_name → stdlib.LoggerFactory.
2. parse_mode=HTML: внешний текст — только через html.escape() ДО подстановки.
3. SQLAlchemy datetime — DateTime(timezone=True) явно.
4. Имя файла после ffmpeg-мёржа/транскода — только через post_hooks.
5. max_filesize молча оставляет .part — проверять размер до скачивания.
6. Пользователю — короткие чистые сообщения, диагностика в лог. error_key, не текст.
7. Большие файлы: request timeout aiogram 60с обрывает upload; retry опасен.
8. yt-dlp без retries/fragment_retries/socket_timeout умирает на столле CDN.
9. arq job_timeout должен быть > download_timeout.
10. i18n: вне контекста апдейта Fluent-ядро ВСЕГДА звать с явной локалью.
11. i18n: core.startup() — КОРУТИНА, всё после await startup().
12. Telegram language_code — только ХИНТ, реальное переключение — /language.
13. yt-dlp переподнимает все ошибки как DownloadError — классифицировать по ТЕКСТУ.
14. bare "Unsupported URL" ≠ наш UnsupportedURLError — различать по форме URL.
15. **11A.0: Alembic revision id ≤ VARCHAR(32). Держать КОРОТКИМ (0004_quality_kind,
    не 0004_download_request_quality_kind). Симптом — StringDataRightTruncationError
    на служебном UPDATE alembic_version, DDL успевает пройти.**
16. **11A.1: провести поле сущности в БД — половина дела. Проверяй звено ЧТЕНИЯ:
    воркер (ProcessDownloadUseCase) строит value objects из сущности — новое поле
    надо ПРОКИНУТЬ явно. Тестировать ЗАХВАТОМ переданных аргументов, не голым моком.**
17. **11C.1: хардкод yt-dlp player_client устаревает и деградирует форматы (у нас
    android/web → только 360p). Не пинить клиент — собственный выбор yt-dlp поспевает
    за YouTube. При деградации форматов/403 — обновлять ВЕРСИЮ yt-dlp (--no-cache).**
18. **11C.2: зелёный локальный pytest ≠ фикс работает. Локальный .venv может иметь
    старую yt-dlp — тесты проверяют лишь СТРОКУ ydl_opts, не реальное скачивание.
    Реальное доказательство — docker-прогон на пересобранном --no-cache образе,
    проверка ffprobe/размера, а не только download_succeeded в логах.**
19. **11C.3: строка из БД — недоверенный вход. Голый конструктор enum
    (`MediaType(row.media_type)`) на нечитаемом значении бросает ValueError из
    get_by_id, то есть УЖЕ ПОСЛЕ «принято» — job падает необработанным, юзер не
    получает ничего. Колонка с правдивым дефолтом деградирует + logger.warning
    (обязательно с request_id, иначе битую строку не найти); колонка без честного
    дефолта (status) поднимает ДОМЕННОЕ исключение с error_key, а не ValueError.
    CHECK-констрейнт это не заменяет: защита нужна на ЧТЕНИИ.**
20. **11C.4: `caplog` при structlog НИЧЕГО не проверяет. structlog в тестах не
    подключён к stdlib logging, `caplog.text` всегда пустой — ассерт «в логах есть X»
    падает, а ассерт «логов нет» проходит ЛОЖНО. Только
    `structlog.testing.capture_logs()`, он же даёт структурные поля (event, log_level,
    kwargs), а не подстроку. Грабли пойманы на СВЕЖЕМ тесте (11C.3), а не в старых:
    аудит `grep -rn caplog tests/` дал НОЛЬ находок — то есть ложной зелени в проекте
    не было, но и ассертов на логи не было вообще, логирование не покрыто нигде.
    Уровень логов в старом коде (что пишем при отказах, есть ли request_id) не
    проверяется ни одним тестом — это открытый долг, а не закрытый вопрос.**
21. **11C.5: любой ad-hoc скрипт, дёргающий `download()`, ОБЯЗАН иметь
    `if __name__ == "__main__":`. `download()` форкает child через `spawn`, тот
    переимпортирует файл скрипта как `__mp_main__` — без guard'а child переигрывает
    весь сценарий с нуля. Наружу это выходит как `exit code 1` дочернего процесса,
    который классификатор превращает в `error-extraction-failed`: СИМПТОМ ПОЛОМКИ
    ИЗВЛЕЧЕНИЯ при полностью исправном коде. Уводит в разбор селекторов/форматов
    вместо обвязки. Симптом-близнец: скрипт, поданный в контейнер через stdin, даёт
    у child `FileNotFoundError: '/app/<stdin>'` — по той же причине, скрипт надо
    монтировать файлом.**
22. **11C.6: ручной фейк-класс, повторяющий доменную сущность, — отложенный 11A.1.
    `_Request` в test_process_download_errors дважды расходился с реальной
    `DownloadRequest` (format_kind, затем quality_kind). Оба раза спасло только то,
    что use case читает новое поле СРАЗУ (падал AttributeError); поле, добавленное
    для более позднего потребителя, разошлось бы молча. В тестах использовать
    настоящую сущность (`DownloadRequest.create(...)`), фейки — только для ПОРТОВ
    (репозитории, нотифаер) и для ORM-модели там, где нужно положить в колонку
    невалидное значение, которое сущность выразить не может.**

## Формат работы с Claude

- **Claude Code работает прямо в репозитории** (не zip-патчи): прямые правки
  файлов + `git diff` для ревью. Этот чат — архитектурный ревьюер: ловит
  скрытые баги ДО кода, требует диагностику до теорий, решает развилки.
- **Диагностика ДО архитектуры, архитектура ДО кода** (правило проекта).
  Пример 11C: не проектировали фикс, пока не увидели вживую, какие форматы
  реально качаются — оказалось, дело в версии, а не в player_client/селекторе.
- Квалити-гейт перед коммитом: `python -m pytest` / `-m ruff check .` /
  `-m mypy --strict src` (локальный Python 3.13 venv).
- **Патчи, меняющие рантайм-инициализацию (main.py, middleware, startup,
  worker) — live-прогон в docker (урок 9.1).**
- **Патчи с миграцией — живой `alembic upgrade head` в docker (урок 11A.0).**
- **Патчи, трогающие извлечение/образ — docker-прогон + проверка ffprobe/
  размера, не только зелёный гейт (урок 11C.2).**
- Кратко: «делаем»/«согласен»/«вариант A» = одобрено, работать автономно.
- Отвечать на русском.

## Не сделано намеренно (YAGNI до своей фазы)

FastAPI/REST, Web/Mobile/Desktop, Premium/Ads/Referral/Payments.
История скачиваний — отложена (данные копятся в download_requests:
format_kind и quality_kind уже там). Когда возьмёмся: `list_by_user` уже
пропускает нечитаемые строки и логирует их, так что одна битая строка не
спрячет всю выдачу.

## git

Day 11C лежит шестью коммитами (см. таблицу дней). Каждый коммит собирался
руками из списка файлов — `git add -A` НЕ использовать: в рабочем дереве
живут untracked-заметки этапов (`CHANGES_11C_stage1.md`,
`STRUCTURE_delta_11C_stage1.md`, `NEW_CHAT_KICKOFF_stage2.md`) — рабочие
леса, уже влитые в CHANGES.md/STRUCTURE.md. Их можно удалить, когда
решишь. `.env` в .gitignore с Day 1.
