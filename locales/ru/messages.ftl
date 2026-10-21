## Universal Media Downloader — русская локаль (Day 9, дополнено Day 10, Day 11A, Day 11B)
## Все строки Presentation-слоя. Ключи сгруппированы по хендлерам.

# --- Кнопки (их ТЕКСТ участвует в роутинге — см. i18n.collect_button_translations) ---
btn-download = ⬇️ Скачать
btn-help = ℹ️ Помощь
btn-confirm = ✅ Скачать
# Day 11A: две кнопки подтверждения под превью (видео / mp3).
btn-confirm-video = ⬇️ Видео
btn-confirm-audio = 🎵 MP3
btn-cancel = ❌ Отмена
# Day 11C: второй шаг видео-флоу — выбор качества. Подписи содержат
# только цифры, поэтому в обеих локалях совпадают; ключи всё равно
# заведены в обеих (паритет ключей — жёсткое правило, см. test_i18n).
btn-quality-720 = 720p
btn-quality-1080 = 1080p
btn-back = ◀️ Назад

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
    3. Выбери «{ btn-confirm-video }» или «{ btn-confirm-audio }» под превью, и я пришлю файл сюда же.

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
# error-bad-url: наша ВАЛИДАЦИЯ allowlist. $reason — наш безопасный текст,
# не диагностика yt-dlp. Остаётся с параметром (Day 9).
error-bad-url = Некорректная ссылка: { $reason }
error-unsupported-site = Этот сайт не поддерживается

# --- Ошибки скачивания/извлечения (Day 10) ---
# Категоризированные сообщения. НИКОГДА не содержат сырого текста yt-dlp
# (баг №6) — только чистый локализованный текст по семантике ошибки.
# error-extraction-failed — generic fallback, БЕЗ параметра (Day 10:
# раньше был { $reason }, теперь сырой reason юзеру не показывается).
error-extraction-failed = Не удалось обработать эту ссылку. Попробуй другую.
error-private = Это приватный аккаунт или контент, для которого нужен вход. Скачать его я не могу.
error-geo = Это видео недоступно в регионе, из которого я к нему обращаюсь. Повторять бесполезно.
error-age = Это видео с возрастным ограничением — для него нужен вход с подтверждённым возрастом, которого у меня нет.
error-unavailable = Это видео удалено или больше не существует. Проверь ссылку.
error-unsupported-media = Похоже, это фото или слайдшоу. Пока я умею скачивать только видео.
error-timeout = Скачивание заняло слишком много времени и было прервано. Попробуй ещё раз.
# $estimated_mb, $limit_mb — числа (Fluent форматирует разряды по локали).
error-too-large = Видео слишком большое для Telegram (~{ $estimated_mb } МБ при лимите { $limit_mb } МБ).
# Доставка (скачали, но не отправилось) — worker-путь.
error-delivery-failed = Скачал видео, но не смог отправить его в Telegram. Попробуй ещё раз позже.
# Внутренний сбой на нашей стороне (Day 11C.3): запись в БД нечитаема.
# Юзеру не за что зацепиться и нечего чинить — поэтому коротко и без
# диагностики (баг #6), она уходит в лог.
error-internal = Что-то сломалось на моей стороне. Попробуй ещё раз — если повторится, отправь ссылку заново.

# --- Прогресс скачивания (Day 11B) ---
# Рендерится ВНЕ контекста апдейта (долгоживущий слушатель в bot-процессе,
# см. progress_listener.py) — только через явную локаль (баг №10).
# $percent — целое число (0-100).
progress-downloading = ⏳ Скачиваю… { $percent }%
# Для стримов без известного total_bytes (percent = None): $mb — число,
# $speed — уже готовая строка вида "1.2 МБ/с" (как $platforms в help-text).
progress-downloading-nostream = ⏳ Скачано { $mb } МБ ({ $speed })
# Day 11B.1 — граница download→постпроцессинг, только audio-путь (mp3).
# Без процента: прогресс самого транскода вне scope.
progress-converting = ⏳ Конвертирую в MP3…

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
health-fail = ❌ Недоступен
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
