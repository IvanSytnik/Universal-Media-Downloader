# Universal Media Downloader — Project Specification (v2)

> Переработанная версия исходного набора документов. Цель правки — убрать внутренние противоречия,
> закрыть архитектурные пробелы, которые приводят к застою и переделкам, и дать чёткие,
> проверяемые критерии "готово" на каждом этапе.

---

## 1. Vision & Goal

Production-ready Telegram-бот для скачивания медиа с поддерживаемых сайтов через yt-dlp,
спроектированный как ядро будущей SaaS-платформы, а не как одноразовый скрипт.

**Важное уточнение относительно "поддержать всё с первого дня":**
это требование применяется к **границам модулей и контрактам** (интерфейсы, Dependency Injection,
разделение слоёв), а НЕ к реализации фич, которые не нужны прямо сейчас.

Правило: *"Проектируй границы так, чтобы Web/API/Mobile могли появиться без переписывания домена.
Не пиши код для Web/API/Mobile, пока не наступила их фаза."*

Это разрешает исходное противоречие между "support all from day one" и YAGNI из Coding Style —
без этого уточнения проект обречён либо на паралич анализа, либо на overengineering.

Юридический контекст: скачивание медиа с YouTube/Instagram/TikTok и т.д. затрагивает ToS
платформ и вопросы авторских прав. До запуска монетизации (Premium/Ads) продукт должен иметь
явную политику использования, ограничения по источникам и процесс реакции на жалобы
правообладателей. Это не блокирует разработку, но должно быть зафиксировано в Roadmap
до Phase "Monetization".

---

## 2. Tech Stack

| Категория | Технология | Примечание |
|---|---|---|
| Язык | Python 3.13 | |
| Telegram | aiogram 3 | async-native |
| API | FastAPI | Phase 5 |
| Downloader | yt-dlp | блокирующая библиотека — см. §6 |
| Медиа | FFmpeg | вызывается как subprocess, не библиотека |
| ORM | SQLAlchemy 2 (async) | |
| Миграции | Alembic | |
| БД | PostgreSQL | |
| Кэш / брокер | Redis | |
| **Task Queue** | **arq** | async-native, работает на Redis, совместим с asyncio-стеком aiogram/FastAPI. Альтернатива — Dramatiq, но он синхронный по умолчанию и потребует лишний слой адаптации |
| Контейнеризация | Docker, Docker Compose | |
| Тесты | pytest, pytest-asyncio, testcontainers | |
| CI/CD | GitHub Actions | |
| Наблюдаемость | structlog, Prometheus, Grafana | |
| Reverse proxy | Nginx | |
| Пакетный менеджер | uv | |
| **JS-рантайм** | **deno** (рекомендуется yt-dlp) | Требуется для `yt-dlp-ejs` — без него полноценная поддержка YouTube деградирует. Обязателен в Docker-образе воркера |

**Важно про ffmpeg:** нужен системный бинарник `ffmpeg`/`ffprobe` (apt/системный пакет),
а НЕ одноимённый pip-пакет с PyPI — это частая ошибка, которая молча ничего не скачивает.

**Решение, требующее фиксации:** task queue выбран — **arq**. Это архитектурное решение первого
уровня, влияет на модель воркеров, деплой и способ передачи прогресса скачивания. Если позже
появится причина сменить (например, нужны сложные workflow/retries как в Celery) — это отдельное
обсуждение с explicit tradeoffs, а не смена "по ходу".

---

## 3. Архитектура

Исходная диаграмма смешивала два разных измерения (слои кода и поток обработки запроса).
Разделяем на два документа.

### 3.1 Layered Architecture (статическая структура, кто от кого зависит)

```
Presentation  →  Application  →  Domain  ←  Infrastructure
```

Правило зависимостей (Dependency Rule):
- **Domain** ни от чего не зависит. Только сущности, value objects, интерфейсы (`Downloader`,
  `Repository`, `Storage`, `Notifier`).
- **Application** зависит только от Domain. Здесь use cases (`RequestDownloadUseCase`,
  `GetHistoryUseCase`) и DTO.
- **Infrastructure** реализует интерфейсы Domain (yt-dlp adapter, SQLAlchemy repo, Redis queue,
  S3 storage). Зависит от Domain, но Domain о ней не знает.
- **Presentation** (Telegram handlers, REST-роуты, admin) вызывает Application use cases.
  Никогда не обращается к Infrastructure напрямую и не содержит бизнес-логику.

### 3.2 Request Flow (поток обработки конкретного скачивания)

```
Telegram Update
   → Handler (Presentation, тонкий, только валидация ввода + вызов use case)
      → RequestDownloadUseCase (Application)
         → создаёт DownloadRequest (Domain entity), кладёт в очередь (arq)
   → Worker (Infrastructure entrypoint)
      → DownloaderPort.download() (реализация — yt-dlp adapter)
      → FFmpeg (при необходимости конвертации)
      → StoragePort.save() (временное хранилище / S3)
   → NotifierPort.notify() → Telegram отправляет файл пользователю
```

Handler и Worker — это два разных **entrypoint** одного и того же Application-слоя, а не два
самостоятельных архитектурных потока. Это ключевое отличие от исходной формулировки.

---

## 4. Folder Structure

Исходная структура (`bot/ api/ worker/ core/ services/ ...`) делит код по типу процесса,
а не по архитектурным слоям — это приводит к тому, что `core/` и `services/` со временем
превращаются в "мусорный ящик". Заменяется на деление по слоям:

```
src/
├── domain/
│   ├── entities/          # User, DownloadRequest, Subscription...
│   ├── interfaces/        # DownloaderPort, RepositoryPort, StoragePort, NotifierPort
│   ├── value_objects/
│   └── exceptions/
├── application/
│   ├── use_cases/         # RequestDownloadUseCase, GetHistoryUseCase...
│   └── dto/
├── infrastructure/
│   ├── downloader/        # yt-dlp adapter
│   ├── database/          # SQLAlchemy models, repositories, Alembic
│   ├── queue/              # arq integration
│   └── storage/            # local tmp storage / S3 adapter
├── presentation/
│   ├── telegram/           # aiogram handlers — тонкие
│   ├── rest_api/            # FastAPI routers (с Phase 5)
│   └── admin/                # с Phase 4
├── workers/                  # entrypoints процессов-воркеров (arq worker settings)
├── config/                    # Pydantic Settings, env-loading
└── shared/                     # логирование, кастомные типы, без бизнес-логики
tests/
    ├── unit/                   # domain + application, без внешних зависимостей
    ├── integration/            # infrastructure, через testcontainers
    └── contract/                # presentation, smoke/contract-тесты
infra/                            # docker, nginx, ci-конфиги, alembic env
scripts/
docs/
```

---

## 5. Доменная модель (черновая, Phase 1)

Исходная документация не содержала ни одной сущности — без этого нельзя закрыть Phase 1
("Database"). Минимальный набор для старта:

- **User** — `id`, `telegram_id` (nullable, один из способов входа, НЕ первичный ключ —
  см. §6 про мультиклиентность), `created_at`, `is_premium`.
- **DownloadRequest** — `id`, `user_id`, `source_url`, `status` (pending/processing/done/failed),
  `media_type`, `created_at`, `completed_at`.
- **DownloadHistory** — производная от DownloadRequest (или тот же объект с историческим статусом).

Subscription, Payment, PromoCode, ReferralLink — проектируются в Phase 4, не раньше.
Не создавать таблицы под них заранее ("на будущее") — это прямое нарушение YAGNI.

---

## 6. Ключевые архитектурные решения, требующие фиксации до кода

### 6.1 Downloader Interface (Domain)

```python
class DownloaderPort(Protocol):
    async def download(
        self,
        url: str,
        options: DownloadOptions,
        progress_callback: Callable[[DownloadProgress], Awaitable[None]] | None = None,
    ) -> DownloadResult: ...
```

- yt-dlp — блокирующая библиотека. В async-воркере она выполняется через
  `run_in_executor` (thread pool) либо в отдельном subprocess — для длительных загрузок
  предпочтителен subprocess, т.к. позволяет убить процесс по таймауту/отмене без риска
  зависания event loop.
- Прогресс скачивания передаётся не напрямую в Telegram, а через `progress_callback` →
  Redis pub/sub → Presentation слушает и обновляет сообщение. Downloader ничего не знает
  о Telegram.

### 6.2 Хранилище файлов

- Telegram Bot API ограничивает размер файла (~50MB через стандартный Bot API,
  до 2GB через локальный Bot API server). "Large files" как Premium-фича из FEATURES.md
  требует решения ещё в Phase 2: либо локальный Bot API server, либо S3/MinIO + прямая ссылка.
- Автоматическая очистка временных файлов — не "когда-нибудь", а конкретный механизм:
  TTL-задача в arq (cron-подобный периодический job), которая чистит файлы старше N минут,
  плюс явный cleanup в `finally` после отправки.

### 6.3 Аутентификация для мультиклиентности

`User.telegram_id` — один из способов входа, не первичный ключ. Для REST API/SDK — API keys,
для Web/Mobile — JWT/OAuth, привязанные к тому же `User.id`. Это закладывается в Phase 1,
даже если сами API keys/JWT появятся только в Phase 5 — иначе миграция потребует переписывать
модель User и все связанные foreign keys.

### 6.4 Интеграция с yt-dlp (уточнение по итогам разбора README)

**Уточнение решения из §6.1:** предпочтителен нативный Python API (`yt_dlp.YoutubeDL`),
а не CLI-обёртка с парсингом stdout. Библиотека даёт напрямую:

- `progress_hooks` — callback на каждый апдейт прогресса, без парсинга текста.
- `match_filter` — фильтрация по длительности/дате/размеру ещё до скачивания (пригодится
  для ограничений Free-тарифа, см. ниже).
- `logger` — перехват debug/info/warning/error вместо парсинга stdout/stderr.
- Кастомные `PostProcessor` — точки расширения для будущих фич (например, добавление
  водяного знака, upload в S3 сразу после скачивания).
- `extract_info(url, download=False)` — можно получить метаданные (заголовок, превью,
  длительность) **без скачивания**, чтобы показать пользователю подтверждение перед
  реальной загрузкой — важно для UX и для отсечения нежелательных запросов до траты ресурсов.

**Блокирующий вызов остаётся проблемой.** `YoutubeDL.download()` — синхронный блокирующий
вызов. Правки по сравнению с §6.1:

- Внутри arq worker-процесса вызов оборачивается в `run_in_executor`, НО для гарантированной
  отмены по таймауту/пользовательской отмене (long-running download) один job лучше выполнять
  в отдельном OS-процессе (`ProcessPoolExecutor` или explicit `multiprocessing.Process`), а не
  в потоке — поток нельзя безопасно убить, процесс можно.
- `progress_hooks` вызываются из чужого потока/процесса. Мост обратно в asyncio — через
  `asyncio.run_coroutine_threadsafe` (при ThreadPoolExecutor) либо через межпроцессную очередь
  (при ProcessPoolExecutor) → Redis pub/sub, как и было решено в §6.1.

**DownloaderPort реализация должна использовать следующие ydl_opts как базовые:**

| Опция | Назначение |
|---|---|
| `restrictfilenames: True` | Санитизация имён файлов силами yt-dlp — не изобретать свою (закрывает пункт Security.md "sanitize filenames") |
| `paths: {'home': ..., 'temp': ...}` | Разделение временной и финальной директории "из коробки" — совпадает с моделью StoragePort (временное хранилище → перенос после успеха) |
| `match_filter` | Ограничения по тарифу: например, для Free — `duration < 3600`, `filesize < 200MB`; для Premium — без ограничений. Реализуется как параметр DownloadOptions, не хардкод |
| `max_filesize` / `retries` / `fragment_retries` | Защита от зависших/аномальных закачек, используется вместо самодельных ретраев |
| `concurrent_fragments` | Регулируемая скорость на основе тарифа (Premium — выше) |
| `logger` + `progress_hooks` | Обязательны всегда — источник структурированных логов и прогресса |

**Двухфазный флоу скачивания (уточнение use case):**

```
1. extract_info(url, download=False) → показать пользователю превью/подтверждение
2. match_filter проверяет лимиты тарифа ДО скачивания
3. download() запускается только после подтверждения (или сразу, если UX не требует превью)
```

Это отдельный use case `PreviewDownloadUseCase`, не только `RequestDownloadUseCase` — стоит
внести в доменную модель Phase 2.

**Cookies / авторизованный контент:** yt-dlp поддерживает `--cookies` и
`--cookies-from-browser`. Для нашего сервера "cookies-from-browser" неприменимо (нет браузера
пользователя на сервере). Если в будущем понадобится доступ к приватному/возрастному контенту —
это отдельное решение уровня Security (хранение credentials/cookies пользователя = чувствительные
данные, шифрование в БД, отдельный consent-flow). На Phase 1-3 не реализуется, но стоит держать
в уме как будущий security-риск, а не откладывать до момента, когда фича внезапно понадобится.

---

## 7. Coding Style

- Production-ready код всегда, никаких прототипов.
- DRY, без дублирования логики.
- Dependency Injection везде, где есть внешняя зависимость (БД, очередь, downloader).
- Полная типизация (mypy strict в CI).
- Интерфейсы (Protocol/ABC) создаются до реализации.
- **Тестирование — без оговорки "whenever practical".** Конкретные пороги:
  - `domain/` и `application/` — 100% покрытие (чистая логика, дёшево тестировать).
  - `infrastructure/` — интеграционные тесты через testcontainers (Postgres, Redis).
  - `presentation/` — smoke/contract-тесты на ключевые сценарии.
  - CI gate: сборка падает при покрытии `domain/application` ниже 85%.
- Публичные методы — docstring с описанием, аргументами, исключениями.

---

## 8. Development Rules

Работа строго по фичам, без забегания вперёд. Каждая фича проходит:

1. Обсуждение архитектуры (альтернативы, tradeoffs, explicit решение).
2. Реализация.
3. Тесты (unit + integration, где применимо).
4. Документация (docstring + обновление docs/ при изменении публичного контракта).
5. Ревью и рефакторинг.

Ничего не помечается "готово", пока не пройдены все 5 пунктов.

---

## 9. Security

- Валидация каждого URL (allowlist поддерживаемых доменов, а не blacklist).
- Санитизация имён файлов, защита от path traversal.
- Экранирование аргументов при вызове FFmpeg/yt-dlp как subprocess — **никогда** не строить
  shell-команду конкатенацией строк, только list-аргументы без `shell=True`.
- Rate limiting на уровне пользователя (Redis-based, per `user_id`) — конкретный лимит
  определяется в Phase 2 при реализации handlers.
- Flood protection на уровне aiogram middleware.
- Secrets только в `.env`, никогда не в коде/логах.
- Никогда не доверять пользовательскому вводу — валидация на границе Presentation, до
  передачи в Application.

---

## 10. Performance & Observability

- Множественные параллельные скачивания через пул arq-воркеров (конфигурируемое
  количество процессов).
- Telegram handlers никогда не блокируются — вся тяжёлая работа только через очередь.
- structlog с structured logging (JSON в проде), correlation ID на каждый DownloadRequest
  для трассировки через все слои.
- Prometheus метрики: количество активных скачиваний, время скачивания, ошибки по типу
  источника, размер очереди.
- Health checks для каждого сервиса в docker-compose (bot, api, worker, postgres, redis).

---

## 11. Roadmap (пересмотренный)

**Phase 1 — Foundation**
Репозиторий, структура по слоям (§4), Docker Compose (postgres, redis), Alembic +
черновая доменная модель (§5), базовый CI (lint + pytest).

**Phase 2 — Core Download Flow**
DownloaderPort + yt-dlp adapter (subprocess-based), arq worker, StoragePort (локальное
хранилище + TTL cleanup), Telegram handlers (тонкие), progress через Redis pub/sub.

**Phase 3 — User Experience**
История скачиваний, настройки, локализация, rate limiting.

**Phase 4 — Monetization**
Subscription/Payment/PromoCode entities, Premium-логика, Referral, Admin Panel,
юридическая политика по источникам (см. §1).

**Phase 5 — Public API**
FastAPI роутеры, API keys, JWT, документация OpenAPI, SDK.

**Phase 6 — Web**
Web-клиент поверх REST API (тот же Application-слой, новый Presentation).

**Phase 7 — Scaling & Ops**
Горизонтальное масштабирование воркеров, CDN для отдачи файлов, продвинутый мониторинг,
локальный Bot API server при необходимости (см. §6.2).

Ads/Analytics распределяются между Phase 4 (базовая статистика) и Phase 7 (полноценная
рекламная система) — в исходном ROADMAP они не были размещены вообще.

---

## 12. Роль ассистента (для CLAUDE.md)

Действовать как Senior Software Architect, Senior Python Engineer, DevOps Engineer,
Security Engineer, QA Engineer.

- Никогда не писать прототипный код — только production-ready.
- Оспаривать плохие архитектурные решения, включая собственные предыдущие, если
  найдены новые обстоятельства.
- Не реализовывать крупные фичи без предварительного обсуждения архитектуры.
- Объяснять tradeoffs явно, а не только финальное решение.
- При конфликте между документацией проекта и запросом пользователя — уточнять,
  а не молча выбирать одну из сторон.
- Отвечать на русском языке.
- Читать все файлы документации проекта перед ответом; PROJECT_SPEC.md — источник истины.