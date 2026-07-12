# Day 10 — Категоризация ошибок yt-dlp + локализованные сообщения

Инкрементальный патч. Распаковать `unzip -o` поверх корня проекта.

## Что сделано

Раньше любой сбой извлечения/скачивания превращался в одно общее
сообщение («не удалось получить информацию»). Теперь ошибки yt-dlp
классифицируются в доменные категории, и пользователь получает чистое
**локализованное** сообщение по семантике сбоя. Реальный повод — TikTok
photo/slideshow пост (`/photo/...`), который yt-dlp отдаёт как
`Unsupported URL`; теперь это честное «фото/слайдшоу, пока не умею», а не
«сайт не поддерживается» и не «попробуй другую ссылку».

### Категории (все — подклассы `ExtractionError`, обратная совместимость)

| Класс | error_key | Когда |
|---|---|---|
| `PrivateContentError` | `error-private` | приватный аккаунт / login-wall |
| `GeoRestrictedError` | `error-geo` | геоблок |
| `AgeRestrictedError` | `error-age` | возрастное ограничение |
| `ContentUnavailableError` | `error-unavailable` | удалено / не существует |
| `UnsupportedMediaError` | `error-unsupported-media` | сайт поддержан, медиа — нет (фото/слайдшоу) |
| `DownloadTimeoutError` | `error-timeout` | скачивание прервано по таймауту |
| `FileTooLargeError` | `error-too-large` | превышен лимит размера (несёт числа) |
| `ExtractionError` (fallback) | `error-extraction-failed` | неопознанное |
| `UnsupportedURLError` | `error-unsupported-site` | реально неподдерживаемый сайт / битая ссылка |

`error_key` — **семантический идентификатор**, не текст: домен не знает
языков. Presentation и worker резолвят его в строку.

## Новые файлы

- `src/infrastructure/downloader/error_classifier.py` — `classify_error(message, url)`:
  yt-dlp сообщение → доменный тип. Матчинг по устойчивым сигнатурам,
  порядок = приоритет. `Unsupported URL` + `/photo/`|`slideshow` →
  `UnsupportedMediaError`; голое → `UnsupportedURLError`. Неопознанное →
  `ExtractionError`. **Сигнатуры проверены на корпусе реальных строк
  yt-dlp** (см. `tests/unit/test_error_classifier.py`).
- `src/domain/interfaces/error_localizer.py` — `ErrorLocalizerPort`
  (`localize(error_key, locale, **kwargs)`). Домен-порт для worker-пути.
- `src/infrastructure/localization/fluent_error_localizer.py` —
  `FluentErrorLocalizer` над тем же Fluent-ядром, что и Telegram-слой, но
  **всегда с явной локалью** (баг #10). Для worker-процесса, где нет
  `I18nContext`.
- `tests/unit/test_error_classifier.py`, `test_error_localizer.py`,
  `test_process_download_errors.py` — 38 тестов.

## Изменённые файлы

- `src/domain/exceptions.py` — добавлены 7 категорий + `error_key` на
  всех. `FileTooLargeError(estimated_mb, limit_mb)` несёт числа.
- `src/infrastructure/downloader/ytdlp_downloader.py` — классификация в
  **обоих** путях: `get_preview` (ловит `DownloadError`) и `download`
  (child-процесс ловит `DownloadError` → тег `extract_error` → родитель
  классифицирует). Сырой текст yt-dlp — **только в лог** (баг #6);
  наружу летит категоризированное исключение с `error_key`. Таймаут и
  too-large получили собственные ключи. Русская строка про размер убрана
  из child-процесса — теперь `FileTooLargeError` с числами (локализуемо).
- `src/application/use_cases/process_download.py` — инжектится
  `error_localizer: ErrorLocalizerPort`. При сбое: `exc.error_key` +
  `user.language` → локализованная строка. **Убраны два бага:** хардкод
  `f"Не удалось скачать: {exc}"` (нелокализованная строка в Application +
  утечка `{exc}` юзеру). Доставка тоже локализована (`error-delivery-failed`).
- `src/presentation/telegram/formatting.py` — новый `format_download_error(i18n, exc)`:
  единая точка `error_key → i18n.get`, `FileTooLargeError` с аргументами.
- `src/presentation/telegram/handlers/preview.py`,
  `handlers/download_flow.py` — используют `format_download_error`.
  **Важно:** `error-bad-url` (наша валидация allowlist, `reason`
  безопасен) и категоризированные ошибки загрузчика — **разные точки
  catch**, чтобы не потерять наш reason и не слить диагностику yt-dlp.
- `src/infrastructure/queue/worker_settings.py` — строит i18n-ядро
  (`await core.startup()`, баг #11) + `FluentErrorLocalizer` в `ctx`.
- `src/infrastructure/queue/jobs.py` — прокидывает `error_localizer` в
  use case.
- `locales/{ru,en}/messages.ftl` — 8 новых ключей (см. таблицу +
  `error-delivery-failed`). **`error-extraction-failed` потерял `{ $reason }`**
  (Day 10: сырой reason юзеру больше не показывается). Локали структурно
  синхронны (47 ключей, проверено).

## Проверено

- `pytest` — 38 новых тестов зелёные (классификатор на реальном корпусе,
  локализатор, worker-путь; проверка «сырой текст не утекает»).
- `ruff check` — чисто.
- `mypy --strict` — чисто.
- **Live-прогон worker-пути** (эмуляция startup + `ProcessDownloadUseCase`
  с реальным `FluentErrorLocalizer`): локализация по `user.language`,
  `None → en`, числовые аргументы, без краша (урок 9.1 — рантайм-
  инициализацию проверять прогоном, не только юнит-тестами).

## ⚠️ Одно поведенческое изменение для проверки в бою

`error-extraction-failed` больше **не принимает** `{ $reason }`. Если
где-то в коде остался вызов `i18n.get("error-extraction-failed", reason=...)`
— лишний аргумент безопасно игнорируется Fluent, но текст reason больше
не покажется (это и была цель — не течь диагностикой). Проверь, что таких
вызовов не осталось (в патче их нет).

## Не сделано (по плану — отдельный день)

Фото/карусели как **скачиваемый** контент (расширение `MediaType.PHOTO`
и логики отправки нескольких файлов). Сейчас фото-пост честно
распознаётся и отклоняется с `error-unsupported-media`.
