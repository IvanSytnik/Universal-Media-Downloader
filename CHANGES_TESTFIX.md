# Day 10 — Test fix (догон 24 упавших теста)

Распаковать `unzip -o` поверх корня проекта. Затем:

```bash
python -m pytest
python -m ruff check .
python -m mypy --strict src
```

## Что чинит

Полный набор был красный из-за 24 упавших тестов, разделённых на две группы.

### Группа B (3 теста) — следствие Day 10, обновлены под новый контракт

`tests/unit/test_ytdlp_downloader.py`:
- Категоризированные ошибки теперь несут `error_key`, а НЕ user-facing текст
  (текст рендерится из FTL ниже по стеку — bug #6). Тесты проверяют ТИП
  исключения и `error_key`, а не строку.
- `test_download_maps_timeout...` → ждёт `DownloadTimeoutError` c
  `error_key="error-timeout"`.
- `test_download_maps_process_error...` → ждёт `error_key="error-extraction-failed"`
  + отсутствие сырого текста (`signed.example` не течёт).
- `test_download_maps_file_too_large...` → `_FileTooLargeError(estimated_mb, limit_mb)`,
  наружу `FileTooLargeError` с числами и `error_key="error-too-large"`.
- `test_get_preview_wraps_ytdlp_download_error` → «Video unavailable»
  классифицируется в `ContentUnavailableError`; проверка `error_key`.

### Группа A (21 тест) — предсуществующий долг (тесты отстали от Day 6/8/9 API)

Эти тесты вызывали функции/конструкторы со СТАРЫМИ сигнатурами и падали
независимо от Day 10 — просто раньше сбор прерывался на `test_download_flow`
и до них не доходил. Обновлены под актуальные сигнатуры:

- `test_bot_factory.py` — `create_dispatcher(i18n_middleware, button_translations,
  storage)` (Day 9). Строим реальный middleware + button_translations из
  стартованного core, FSM = MemoryStorage.
- `test_formatting.py` — два `MediaPreview(...)` получили недостающие
  `source_url`/`thumbnail_url`.
- `test_help_formatting.py` — `format_help(i18n, settings)` /
  `format_retry_after(i18n, seconds)` (Day 9) — добавлен i18n.
- `test_preview_formatting.py` — `format_preview(i18n, preview)` (Day 9).
- `test_process_download_use_case.py` — конструктор получил `error_localizer`
  (Day 10) + `download_timeout_seconds` (Day 8.2). Failure-путь проверяет
  ЛОКАЛИЗОВАННОЕ сообщение (не сырой текст).
- `test_telegram_notifier.py` — `TelegramNotifier(..., file_upload_timeout_seconds=...)`
  (Day 8.1).

## Новый файл

- `tests/conftest.py` — общие `FakeI18n` и `FakeErrorLocalizer` над РЕАЛЬНЫМ
  стартованным Fluent core (тесты гоняют настоящий FTL, не заглушки) +
  фикстура `i18n_core`. Вынесено, чтобы не дублировать по файлам (DRY).
  `FakeI18n.get(key, locale=None, /, **kwargs)` — принимает позиционную
  локаль (нужно `main_menu_keyboard`), в отличие от локального фейка в
  старом `test_formatting.py`.

## Проверено (в песочнице)

- `ruff check` — чисто по всем 8 файлам.
- `py_compile` — все компилируются.
- Логика правок соответствует сигнатурам из присланного кода
  (main.py, worker_settings.py, formatting.py, process_download.py Day 10).

Прогон полного `pytest` — на твоей стороне (в песочнице нет полного `src/`).
Ожидается зелёный набор целиком.
