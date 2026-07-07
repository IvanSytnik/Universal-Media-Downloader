# Day 8 — Rate limiting, постоянная клавиатура, /help

## Интеграция

```bash
cd путь/к/umd
unzip -o umd_day8_patch.zip
docker compose up -d --build bot
```

Миграций БД нет. Новые настройки имеют дефолты — `.env` менять не обязательно.

## Новые файлы

- `src/domain/interfaces/rate_limiter.py` — `RateLimiterPort` + `RateLimitResult`.
  Лимиты — аргументы вызова, не состояние лимитера (задел под тарифы Phase 4).
- `src/infrastructure/rate_limit/__init__.py`
- `src/infrastructure/rate_limit/redis_rate_limiter.py` — sliding window на ZSET
  (точный лимит без краевого 2×-эффекта fixed window). Отклонённые попытки НЕ
  записываются — долбёжка не отодвигает разблокировку. `retry_after` из самого
  старого события окна.
- `tests/unit/test_rate_limiter.py` — 6 тестов (fake Redis с реальной
  ZSET-семантикой).
- `tests/unit/test_help_formatting.py` — 5 тестов.

## Изменённые файлы

- `src/config/settings.py` — `rate_limit_downloads_per_hour=10`,
  `rate_limit_previews_per_minute=5`. Переопределяются через env
  (`RATE_LIMIT_DOWNLOADS_PER_HOUR=...`).
- `src/presentation/telegram/keyboards.py` — `main_menu_keyboard()` теперь
  постоянная нижняя `ReplyKeyboardMarkup` («⬇️ Скачать» / «ℹ️ Помощь»,
  `is_persistent`, placeholder в поле ввода). Константы `BTN_DOWNLOAD`/`BTN_HELP`.
- `src/presentation/telegram/formatting.py` — `format_help(settings)`:
  платформы генерируются из allowlist, лимиты из настроек (док не разъезжается
  с поведением); `format_retry_after` (минуты округляются вверх).
- `src/presentation/telegram/handlers/download_flow.py`:
  - текстовые хендлеры кнопок reply-клавиатуры (зарегистрированы ДО
    FSM-хендлера — «ℹ️ Помощь» в состоянии waiting_for_url показывает помощь,
    а не «Некорректная ссылка»);
  - preview-лимит в `_show_preview` (обе точки входа одной проверкой);
    валидация URL идёт ДО лимита — опечатка не сжигает слот;
  - download-лимит в ✅-confirm; порядок: токен → лимит → consume — отказ по
    лимиту не сжигает превью, после кулдауна та же кнопка работает;
  - старые inline-хендлеры `flow:*` сохранены (кнопки под старыми /start
    работают), захардкоженный `_HELP_TEXT` удалён.
- `src/presentation/telegram/handlers/download.py` — тот же download-лимит в
  `/download`, общий namespace ключа `download:<id>` с confirm-кнопкой (две
  точки входа не складываются в двойной лимит).
- `src/presentation/telegram/handlers/basic.py` — `/help`; текст `/start`
  обновлён под постоянную клавиатуру.
- `src/main.py` — DI `rate_limiter`, `bot.set_my_commands(...)` (синяя
  menu-кнопка: start/download/preview/help).
- `tests/unit/test_download_flow.py` — тест меню обновлён под reply-клавиатуру.
- `infra/alembic/env.py` — попутный фикс сортировки импортов (ruff I001,
  был в baseline).

## Известный компромисс

`RedisRateLimiter.acquire` — check и record двумя командами (не Lua): два
строго одновременных запроса одного юзера на границе лимита могут дать +1
событие. Для per-user Telegram-трафика недостижимо; если понадобится для REST
API (Phase 5) — маленький EVAL за тем же портом, вызывающий код не меняется.

## Квалити-гейт

pytest: **116 passed** (было 105, +11) · ruff: чисто · mypy strict (src): чисто.

## Ручной smoke-чеклист

1. `/start` — снизу постоянная клавиатура, в поле ввода placeholder.
2. «ℹ️ Помощь» и `/help` — одинаковый текст с платформами и лимитами.
3. 6 превью подряд за минуту — шестое отбивается «Попробуй через N сек».
4. 11-е скачивание за час — alert «Лимит исчерпан…», превью НЕ сгорает:
   после ожидания ✅ на той же карточке работает.
5. Синяя menu-кнопка слева от поля ввода — 4 команды.
docker compose up --build