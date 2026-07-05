# Day 7 — Кнопки, единый флоу «превью → подтверждение → скачивание», allowlist доменов

## Что нового

1. **`/start` с inline-кнопками** [⬇️ Скачать] [ℹ️ Помощь].
2. **Единый флоу**: кнопка «Скачать» → «пришли ссылку» → превью с кнопками
   [✅ Скачать] [❌ Отмена] → очередь → файл. Плюс: голая ссылка сообщением
   (без команд и кнопок) сразу запускает превью.
3. **FSM на RedisStorage** — состояние «жду ссылку» переживает рестарт бота.
4. **PreviewContextStore** — URL хранится в Redis по короткому токену
   (callback_data лимит 64 байта), TTL 10 минут; протухшая кнопка отвечает
   «превью устарело», повторный тап ✅ не создаёт дубль скачивания.
5. **Allowlist доменов** (SECURITY.md): по умолчанию YouTube, youtu.be,
   TikTok, Instagram, Twitter/X, VK. Переопределяется через env.
   Проверка — на границе Presentation; use cases не менялись.
6. `/preview` и `/download` работают как раньше.

## Интеграция

```bash
cd путь/к/проекту
unzip -o umd-day7-patch.zip
docker compose up -d --build bot
```

Миграций БД нет. Новых контейнеров нет. Новых переменных в .env не требуется
(всё имеет дефолты).

## Новые настройки (опционально, в .env)

```
# JSON-список; пустой список [] = разрешить все сайты (только для dev!)
ALLOWED_DOMAINS=["youtube.com","youtu.be","tiktok.com","instagram.com","twitter.com","x.com","vk.com"]
PREVIEW_CONTEXT_TTL_SECONDS=600
```

## Файлы

Новые:
- src/domain/interfaces/preview_context_store.py — порт token→URL
- src/infrastructure/preview_context/{__init__,redis_preview_context_store}.py
- src/presentation/telegram/keyboards.py — inline-клавиатуры
- src/presentation/telegram/states.py — FSM DownloadFlow.waiting_for_url
- src/presentation/telegram/formatting.py — общий формат превью
  (вынесен из preview.py: теперь нужен двум хендлерам, DRY)
- src/presentation/telegram/handlers/download_flow.py — весь новый флоу
- tests/unit/test_url_allowlist.py, test_preview_context_store.py,
  test_download_flow.py

Изменённые:
- src/config/settings.py — allowed_domains, preview_context_ttl_seconds
- src/domain/value_objects/url_validation.py — validate_url_against_allowlist
  (суффикс по меткам: youtube.com покрывает www./m., но НЕ evilyoutube.com)
- src/presentation/telegram/handlers/basic.py — /start с кнопками
- src/presentation/telegram/handlers/preview.py — формат превью из общего модуля
- src/presentation/telegram/bot.py — FSM storage, download_flow_router
  подключён ПОСЛЕДНИМ (иначе перехватывал бы команды со ссылками)
- src/main.py — Redis-клиент, RedisStorage, preview_store в start_polling
- tests/unit/test_preview_formatting.py — импорт из formatting.py

## Ключевые решения

- **FSM в Redis, не в памяти**: рестарт бота не сбрасывает «жду ссылку»;
  готово к нескольким инстансам бота (Phase 7).
- **Токен вместо URL в callback_data**: лимит Telegram 64 байта. uuid4.hex
  (32 символа) + TTL = заодно защита от протухших кнопок и от дублей
  (токен удаляется ДО постановки в очередь).
- **Allowlist на границе Presentation**, use cases зовут прежний
  структурный validate_url — сигнатуры Application-слоя не тронуты.
- **_looks_like_url — роутинг, не валидация**: только http(s)://-префикс,
  чтобы обычный текст («привет») молча игнорировался, а не получал
  ошибку валидации.

## Проверено

pytest: 105 passed (было 79) · ruff: clean · mypy strict: clean
