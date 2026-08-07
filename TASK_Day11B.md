# TASK — Day 11B: Прогресс скачивания в реальном времени

> Этот файл — задача для реализации в **Claude Code**. Перед началом ОБЯЗАТЕЛЬНО
> прочитать `PROJECT_SPEC.md` (источник истины), `HANDOFF.md`, `STRUCTURE.md`.
> Архитектура ниже согласована ДО кода. Работать по 5-шаговой дисциплине
> (§8 PROJECT_SPEC): архитектура → реализация → тесты → документация → ревью.
> Отвечать и комментировать на русском.

---

## Цель

Показывать пользователю прогресс скачивания в реальном времени, редактируя
сообщение-превью («⏳ N%» / байты+скорость для стримов). Это последний пункт
**Phase 2 — Core Download Flow**. После него проект = beta-MVP-ready.

## Ключевой инвариант (не нарушать)

Downloader и domain НИЧЕГО не знают о Telegram (Dependency Rule, PROJECT_SPEC §6.1).
Прогресс идёт: child-процесс → IPC → родитель → Redis pub/sub → bot-слушатель →
`editMessageText`. Вся Telegram-специфика (троттлинг, «message is not modified»,
message_id) живёт ТОЛЬКО в presentation/infrastructure, не в домене.

---

## Архитектура (согласована, реализовать как есть)

### Поток данных
```
progress_hooks (child-процесс скачивания)
  → multiprocessing.Queue (IPC, как уже сделано для extract_error)
    → родитель дренит в отдельной asyncio-задаче
      → ProgressPublisherPort.publish(request_id, DownloadProgress)
        → RedisProgressPublisher → Redis PUBLISH umd:progress:<request_id>
          → долгоживущий слушатель в bot-процессе (SUBSCRIBE umd:progress:*)
            → throttled editMessageText «⏳ N%»
```

### Новые компоненты

**domain:**
- `value_objects/download_progress.py` — `DownloadProgress`: `percent: float | None`,
  `downloaded_bytes: int`, `total_bytes: int | None`, `speed: float | None`,
  `eta: int | None`. Frozen dataclass. `percent` = None когда `total_bytes` None
  (стримы) — потребитель показывает байты/скорость.
- `interfaces/progress_publisher.py` — `ProgressPublisherPort` (Protocol):
  `async def publish(self, request_id: int, progress: DownloadProgress) -> None`.

**infrastructure:**
- `progress/redis_progress_publisher.py` — `RedisProgressPublisher`, реализует порт,
  PUBLISH JSON в канал `umd:progress:<request_id>`. Сериализация DownloadProgress →
  dict → json. Redis-клиент инжектится.
- (слушатель — в presentation, см. ниже; publisher — infra)

**application:**
- `ProcessDownloadUseCase` — инжектить `progress_publisher: ProgressPublisherPort`.
  Прокинуть `progress_callback` в `downloader.download(...)` (сигнатура порта уже
  имеет `progress_callback`, §6.1). Callback строит DownloadProgress из сырых данных
  hook и зовёт `progress_publisher.publish(request_id, progress)`.

**presentation (bot-процесс):**
- Долгоживущий asyncio-слушатель `umd:progress:*` рядом со `start_polling` в `main.py`
  (вариант А — тот же процесс, прямой доступ к `bot`). psubscribe на паттерн,
  парсит request_id из канала, резолвит (chat_id, message_id) — см. ниже про payload —
  делает throttled `editMessageText`.
- Троттлинг: не чаще 1/3с И шаг ≥5%. Глушить исключение «message is not modified».
  Дебаунс-состояние (last_percent, last_ts per request_id) — в слушателе, in-memory.
- Финал: при 100% / завершении редактируем ТО ЖЕ сообщение (не шлём новое), затем
  штатная отправка файла идёт как раньше.

### Координаты сообщения — В PAYLOAD ЗАДАЧИ (НЕ в домене)

Контраст с format_kind (Day 11A — доменное свойство). chat_id + message_id — деталь
ТРАНСПОРТА (КУДА рисовать прогресс). Расширить сигнатуру задачи:
```
download_job(ctx, request_id, chat_id, message_id)
```
message_id — id отредактированной превью-карточки (бот его уже знает при постановке
в очередь). Слушателю нужна связка request_id → (chat_id, message_id): передавать её
через сам pub/sub-канал НЕ надо — слушатель узнаёт координаты иначе. Выбрать чистый
путь: либо публиковать (chat_id, message_id) в payload прогресс-сообщения, либо
слушатель читает их из download_requests/Redis. РЕШЕНИЕ: включить chat_id+message_id
в JSON прогресс-события (они уже есть в payload задачи, воркер их знает и кладёт в
каждое событие) — слушатель самодостаточен, не ходит в БД на каждом апдейте.

### IPC для progress_hooks

progress_hooks вызываются в child-процессе (multiprocessing.Process, как в Day 5).
Мост в родителя — через существующую/новую multiprocessing.Queue (тот же механизм,
что уже несёт extract_error). Родитель дренит очередь в asyncio-задаче параллельно
ожиданию завершения процесса, каждое событие → publish. НЕ блокировать event loop:
дренаж через `run_in_executor` на `queue.get` с таймаутом, либо `asyncio.Queue` мост.
Выбрать неблокирующий вариант, объяснить в CHANGES.md.

---

## i18n

Новые ключи в `locales/{ru,en}/messages.ftl` (структурная синхронность обязательна,
тест это проверяет):
- `progress-downloading` — «⏳ Скачиваю… { $percent }%» / «⏳ Downloading… { $percent }%»
- `progress-downloading-nostream` — для total=None: байты + скорость
  («⏳ Скачано { $mb } МБ ({ $speed })»).
Слушатель вне контекста апдейта → звать Fluent-ядро с ЯВНОЙ локалью (баг #10),
через FluentErrorLocalizer-подобный путь или прямой core с user.language.
Локаль юзера тянуть из request (есть в БД) — положить language в прогресс-событие
ИЛИ резолвить один раз при старте прогресса. РЕШЕНИЕ: положить language в JSON
прогресс-события (воркер знает user.language из запроса) — слушатель не ходит в БД.

---

## Тесты (обязательно, пороги §7)

- `DownloadProgress` — конструирование, percent=None при total=None.
- `RedisProgressPublisher` — publish сериализует корректный JSON в правильный канал
  (fake redis / мок PUBLISH).
- `ProcessDownloadUseCase` — progress_callback вызывает publisher (захват аргумента,
  как регресс-страж 11A.1: fake publisher пишет полученный DownloadProgress, тест
  сверяет).
- Троттлинг слушателя — юнит на дебаунс-логику (1/3с И ≥5%), в т.ч. глушение
  «not modified».
- i18n — новые ключи присутствуют в обеих локалях (существующий тест синхронности
  подхватит).

## Квалити-гейт (перед готовностью)

- `python -m pytest` — все зелёные (было 197 → станет больше).
- `python -m ruff check .` — чисто.
- `python -m mypy --strict src` — чисто.

## ⚠️ ОБЯЗАТЕЛЬНЫЙ LIVE-ПРОГОН (урок 9.1)

Патч трогает worker + bot startup (новая asyncio-задача-слушатель, расширенная
сигнатура задачи). Юнит-тесты НЕ ловят рантайм-краши инициализации. Требуется
живой прогон в docker:
1. `docker compose up` (bot + worker + redis + postgres + telegram-bot-api).
2. Реальное скачивание видео → убедиться: сообщение-превью редактируется
   прогрессом, шаг ≥5%, не чаще 1/3с, финал → отправка файла в то же сообщение.
3. mp3-путь → прогресс тоже идёт (транскод после — прогресс до 100% на download-фазе).
4. Стрим без total (если найдётся) → показ байтов/скорости без падения на percent=None.

## Не расширять scope (YAGNI)

Только прогресс скачивания. НЕ трогать: фото/карусели, историю, Premium, метрики
Prometheus. Прогресс постпроцессинга (ffmpeg-транскод mp3) — вне scope Day 11B,
достаточно download-фазы.

## Документация на выходе

- `CHANGES.md` — что сделано, новые/изменённые файлы, объяснение неблокирующего
  дренажа IPC, решение по координатам в payload.
- Обновить `HANDOFF.md` и `STRUCTURE.md` (полные версии на замену): отметить Day 11B
  выполненным, обновить счётчик тестов, зафиксировать новые баги если всплывут.
- git: коммит Day 11B; проверить, что .env не попадает.
