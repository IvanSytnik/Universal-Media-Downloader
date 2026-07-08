## Universal Media Downloader — русская локаль (Day 9)
## Все строки Presentation-слоя. Ключи сгруппированы по хендлерам.

# --- Кнопки (их ТЕКСТ участвует в роутинге — см. i18n.collect_button_translations) ---
btn-download = ⬇️ Скачать
btn-help = ℹ️ Помощь
btn-confirm = ✅ Скачать
btn-cancel = ❌ Отмена

# --- Меню-команды (set_my_commands) ---
cmd-start = Главное меню
cmd-download = Скачать по ссылке
cmd-preview = Информация о видео
cmd-help = Помощь и лимиты

# --- /start ---
start-greeting =
    Привет! Это Universal Media Downloader.

    Пришли ссылку на видео (YouTube, TikTok, Instagram и другие) — покажу превью и скачаю по подтверждению.

    Кнопки внизу экрана всегда под рукой: «{ btn-download }» и «{ btn-help }».

# --- Приглашение прислать ссылку (кнопка «Скачать» / состояние FSM) ---
flow-send-url = Пришли ссылку на видео — покажу превью перед скачиванием.

# --- /help ---
# $platforms — уже готовая строка (allowlist), $downloads / $previews / $filesize — числа.
help-text =
    Я скачиваю видео по ссылке с поддерживаемых сайтов.

    Поддерживаемые платформы:
    { $platforms }

    Как пользоваться:
    1. Нажми «{ btn-download }» внизу или просто пришли ссылку сообщением.
    2. Я покажу превью — название, автора, длительность.
    3. Нажми «{ btn-confirm }» под превью, и я пришлю файл сюда же.

    Команды:
    /preview ссылка — только информация о видео
    /download ссылка — скачать сразу, без превью
    /help — это сообщение

    Лимиты:
    — до { $downloads } { $downloads ->
        [one] скачивания
        [few] скачиваний
       *[many] скачиваний
    } в час
    — до { $previews } { $previews ->
        [one] превью
       *[other] превью
    } в минуту
    — файлы до { $filesize } МБ

# --- Превью ---
preview-fetching = 🔍 Получаю информацию о видео…
# $title, $uploader — экранируются в коде (html.escape) ДО подстановки.
preview-card =
    📹 { $title }
    Автор: { $uploader }
    Длительность: { $duration }
    Тип: { $mediatype }
preview-uploader-unknown = неизвестно
preview-duration-unknown = неизвестно

# --- Подтверждение / отмена скачивания ---
flow-download-started =

    ⏳ Скачивание начато — пришлю файл сюда же, когда будет готово.
flow-cancelled =

    ❌ Отменено.
flow-preview-stale = Превью устарело — пришли ссылку ещё раз.

# --- Ошибки ссылок ---
error-bad-url = Некорректная ссылка: { $reason }
error-extraction-failed = Не удалось получить информацию: { $reason }
error-unsupported-site = Этот сайт не поддерживается

# --- /download ---
download-usage = Использование: /download ссылка
download-started =
    Скачивание начато — это может занять от нескольких секунд до нескольких минут в зависимости от размера видео.
    Пришлю файл сюда же, когда будет готово.

# --- /preview ---
preview-usage = Использование: /preview ссылка

# --- Rate limiting ---
# $seconds — целое; форматирование "сек/мин" выбирается селектором.
rate-limit-seconds = Слишком часто. Попробуй через { $seconds } { $seconds ->
        [one] секунду
        [few] секунды
       *[many] секунд
    }.
rate-limit-minutes = Лимит исчерпан. Попробуй через { $minutes } { $minutes ->
        [one] минуту
        [few] минуты
       *[many] минут
    }.

# --- Health / worker ---
health-postgres = Postgres: { $status }
health-redis = Redis: { $status }
health-ok = ✅ OK
worker-ping-enqueued =
    Задача поставлена в очередь.
    Job ID: { $jobid }

    Проверь результат через несколько секунд: /worker_status
worker-status-empty =
    Воркер ещё не обработал ни одной ping-задачи.
    Сначала выполни /worker_ping
worker-status =
    Последняя обработанная ping-задача:
    Сообщение: { $message }
    Обработана: { $processed }

help-any-site = любые сайты, которые поддерживает yt-dlp
flow-placeholder = Пришли ссылку на видео…

# --- /language (выбор языка) ---
language-prompt = Выбери язык / Choose your language:
btn-lang-ru = 🇷🇺 Русский
btn-lang-en = 🇬🇧 English
language-changed = Язык переключён на русский.
cmd-language = Сменить язык
