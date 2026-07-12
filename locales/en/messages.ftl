## Universal Media Downloader — English locale (Day 9, extended Day 10)
## Same keys as ru/messages.ftl. Missing a key here is a hard error
## (raise_key_error=True), so both locales stay structurally in sync.

# --- Buttons (their TEXT drives routing) ---
btn-download = ⬇️ Download
btn-help = ℹ️ Help
btn-confirm = ✅ Download
btn-cancel = ❌ Cancel

# --- Menu commands (set_my_commands) ---
cmd-start = Main menu
cmd-download = Download by link
cmd-preview = Video info
cmd-help = Help and limits

# --- /start ---
start-greeting =
    Hi! This is Universal Media Downloader.

    Send a link to a video (YouTube, TikTok, Instagram and others) — I'll show a preview and download it once you confirm.

    The buttons at the bottom are always at hand: “{ btn-download }” and “{ btn-help }”.

# --- Prompt to send a link ---
flow-send-url = Send a video link — I'll show a preview before downloading.

# --- /help ---
help-text =
    I download videos by link from supported sites.

    Supported platforms:
    { $platforms }

    How to use:
    1. Tap “{ btn-download }” below or just send a link as a message.
    2. I'll show a preview — title, author, duration.
    3. Tap “{ btn-confirm }” under the preview and I'll send the file right here.

    Commands:
    /preview link — video info only
    /download link — download immediately, no preview
    /help — this message

    Limits:
    — up to { $downloads } { $downloads ->
        [one] download
       *[other] downloads
    } per hour
    — up to { $previews } { $previews ->
        [one] preview
       *[other] previews
    } per minute
    — files up to { $filesize } MB

# --- Preview ---
preview-fetching = 🔍 Fetching video info…
preview-card =
    📹 { $title }
    Author: { $uploader }
    Duration: { $duration }
    Type: { $mediatype }
preview-uploader-unknown = unknown
preview-duration-unknown = unknown

# --- Confirm / cancel ---
flow-download-started =

    ⏳ Download started — I'll send the file here when it's ready.
flow-cancelled =

    ❌ Cancelled.
flow-preview-stale = The preview has expired — send the link again.

# --- URL errors ---
# error-bad-url: OUR allowlist validation. $reason is our own safe text,
# not yt-dlp diagnostics. Keeps its parameter (Day 9).
error-bad-url = Invalid link: { $reason }
error-unsupported-site = This site is not supported

# --- Download / extraction errors (Day 10) ---
# Categorized messages. NEVER contain raw yt-dlp text (bug #6) — clean
# localized text keyed by error semantics only.
# error-extraction-failed — generic fallback, NO parameter (Day 10:
# was { $reason }; raw reason is no longer shown to the user).
error-extraction-failed = Couldn't process this link. Try another one.
error-private = This is a private account or login-only content. I can't download it.
error-geo = This video is blocked in the region I'm requesting it from. Retrying won't help.
error-age = This video is age-restricted and needs a signed-in, age-verified session I don't have.
error-unavailable = This video was removed or no longer exists. Double-check the link.
error-unsupported-media = This looks like a photo or slideshow. I can only download videos for now.
error-timeout = The download took too long and was aborted. Please try again.
# $estimated_mb, $limit_mb — numbers (Fluent formats digit grouping per locale).
error-too-large = This video is too large for Telegram (~{ $estimated_mb } MB, limit { $limit_mb } MB).
# Delivery (downloaded but couldn't send) — worker path.
error-delivery-failed = I downloaded the video but couldn't send it to Telegram. Please try again later.

# --- /download ---
download-usage = Usage: /download link
download-started =
    Download started — this may take from a few seconds to a few minutes depending on the video size.
    I'll send the file here when it's ready.

# --- /preview ---
preview-usage = Usage: /preview link

# --- Rate limiting ---
rate-limit-seconds = Too frequent. Try again in { $seconds } { $seconds ->
        [one] second
       *[other] seconds
    }.
rate-limit-minutes = Limit reached. Try again in { $minutes } { $minutes ->
        [one] minute
       *[other] minutes
    }.

# --- Health / worker ---
health-postgres = Postgres: { $status }
health-redis = Redis: { $status }
health-ok = ✅ OK
worker-ping-enqueued =
    Task enqueued.
    Job ID: { $jobid }

    Check the result in a few seconds: /worker_status
worker-status-empty =
    The worker hasn't processed any ping task yet.
    Run /worker_ping first
worker-status =
    Last processed ping task:
    Message: { $message }
    Processed: { $processed }

help-any-site = any site supported by yt-dlp
flow-placeholder = Send a video link…

# --- /language ---
language-prompt = Выбери язык / Choose your language:
btn-lang-ru = 🇷🇺 Русский
btn-lang-en = 🇬🇧 English
language-changed = Language switched to English.
cmd-language = Change language
