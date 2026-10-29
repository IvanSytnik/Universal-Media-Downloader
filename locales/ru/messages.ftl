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
# $height — лучшая короткая сторона источника, например "900" (строка).
btn-quality-best = { $height }p (лучшее)
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
    3. Выбери «{ btn-confirm-video }» или «{ btn-confirm-audio }» под превью (для видео спрошу качество, если есть выбор), и я пришлю файл сюда же.

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
preview-title-unknown = Без названия
preview-uploader-unknown = неизвестно
preview-duration-unknown = неизвестно

# --- Подтверждение / отмена скачивания ---
flow-download-started =

    ⏳ Скачивание начато — пришлю файл сюда же, когда будет готово.
# $error — a localized error-* message (Fluent strings, never raw exception text).
flow-download-failed =

    ❌ { $error }
flow-cancelled =

    ❌ Отменено.
flow-preview-stale = Превью устарело — пришли ссылку ещё раз.
# Обычный текст, а не ссылка, которую мы маршрутизируем (нет http:// или https://).
hint-send-link = Пришли ссылку, которая начинается с https://

# --- Ошибки ссылок ---
# НАША валидация (url_validation.py), по ключу на причину отказа.
# error-unsupported-site покрывает и BLOCKED_DOMAINS, и «Unsupported URL»
# самого yt-dlp — списка сайтов там нет намеренно.
error-url-empty = Ссылка пустая.
error-url-scheme = Поддерживаются только ссылки http:// и https://.
error-url-no-host = В ссылке нет домена.
# $domains — allowlist, уже склеенный через ", ".
error-url-domain-not-allowed = Этот сайт не поддерживается. Поддерживаются: { $domains }
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
error-preview-timeout = Не удалось вовремя получить данные по ссылке. Попробуй ещё раз чуть позже.
# $estimated_mb, $limit_mb — числа (Fluent форматирует разряды по локали).
error-too-large = Видео слишком большое для Telegram (~{ $estimated_mb } МБ при лимите { $limit_mb } МБ).
# Доставка (скачали, но не отправилось) — worker-путь.
error-delivery-failed = Скачал видео, но не смог отправить его в Telegram. Попробуй ещё раз позже.
# Reaper: запрос завис (воркер упал или job не завершился) и был закрыт.
error-request-stale = Не получилось обработать запрос — он завис и был отменён. Отправь ссылку ещё раз.
# Disk guard: мало места под загрузки, скачивание не начиналось.
error-storage-full = Я сейчас перегружен и не могу начать скачивание. Попробуй через несколько минут.
# Внутренний сбой на нашей стороне (Day 11C.3): запись в БД нечитаема.
# Юзеру не за что зацепиться и нечего чинить — поэтому коротко и без
# диагностики (баг #6), она уходит в лог.
error-internal = Что-то сломалось на моей стороне. Попробуй ещё раз — если повторится, отправь ссылку заново.
# Day 11C: kill-switch FormatPolicy — этот формат выключен для источника.
error-format-not-allowed = Этот формат сейчас недоступен для этого сайта. Отправь ссылку заново — покажу, что доступно.

# --- Прогресс скачивания (Day 11B) ---
# Рендерится ВНЕ контекста апдейта (долгоживущий слушатель в bot-процессе,
# см. progress_listener.py) — только через явную локаль (баг №10).
# $percent — целое число (0-100).
progress-downloading = ⏳ Скачиваю… { $percent }%
# Для стримов без известного total_bytes (percent = None): $mb — число,
# $speed — уже готовая строка: progress-speed или "?", если скорость
# неизвестна (как $platforms в help-text).
progress-downloading-nostream = ⏳ Скачано { $mb } МБ ({ $speed })
# $speed — МБ/с уже отформатированной строкой ("1.2"), не NUMBER.
progress-speed = { $speed } МБ/с
# Day 11B.1 — граница download→постпроцессинг, только audio-путь (mp3).
# Без процента: прогресс самого транскода вне scope.
progress-converting = ⏳ Конвертирую в MP3…
# Day 11D-2 — финальные состояния карточки. Коротко намеренно: причина
# ошибки приходит отдельным сообщением.
progress-uploading = ⏳ Отправляю файл…
progress-done = ✅ Отправлено
progress-failed = ❌ Не удалось

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
