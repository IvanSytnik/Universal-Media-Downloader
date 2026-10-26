## Universal Media Downloader — English locale (Day 9, extended Day 10, Day 11A, Day 11B)
## Same keys as ru/messages.ftl. Missing a key here is a hard error
## (raise_key_error=True), so both locales stay structurally in sync.

# --- Buttons (their TEXT drives routing) ---
btn-download = ⬇️ Download
btn-help = ℹ️ Help
btn-confirm = ✅ Download
# Day 11A: two confirm buttons under the preview (video / mp3).
btn-confirm-video = ⬇️ Video
btn-confirm-audio = 🎵 MP3
btn-cancel = ❌ Cancel
# Day 11C: step 2 of the video flow — quality picker. The tier labels
# are digits only, so they read the same in both locales; the keys
# exist in both regardless (key parity is a hard rule, see test_i18n).
btn-quality-720 = 720p
btn-quality-1080 = 1080p
# $height — the source's own best short side, e.g. "900" (a string).
btn-quality-best = { $height }p (best)
btn-back = ◀️ Back

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
    3. Choose “{ btn-confirm-video }” or “{ btn-confirm-audio }” under the preview (for video I'll ask about quality if there's a choice) and I'll send the file right here.

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
# $error — a localized error-* message (Fluent strings, never raw exception text).
flow-download-failed =

    ❌ { $error }
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
error-preview-timeout = Couldn't fetch the link's details in time. Please try again a bit later.
# $estimated_mb, $limit_mb — numbers (Fluent formats digit grouping per locale).
error-too-large = This video is too large for Telegram (~{ $estimated_mb } MB, limit { $limit_mb } MB).
# Delivery (downloaded but couldn't send) — worker path.
error-delivery-failed = I downloaded the video but couldn't send it to Telegram. Please try again later.
# Reaper: the request stalled (worker crash or an unfinished job) and was closed.
error-request-stale = I couldn't finish this request — it got stuck and was cancelled. Please send the link again.
# Disk guard: too little disk space for downloads, nothing was started.
error-storage-full = I'm overloaded right now and can't start the download. Please try again in a few minutes.
# Internal failure on our side (Day 11C.3): a database row is unreadable.
# Nothing for the user to act on, so keep it short and free of
# diagnostics (bug #6) — those go to the log.
error-internal = Something broke on my side. Please try again — if it keeps happening, send the link once more.
# Day 11C: FormatPolicy kill-switch — this format is switched off for the source.
error-format-not-allowed = This format isn't available for this site right now. Send the link again to see what is.

# --- Download progress (Day 11B) ---
# Rendered OUTSIDE an update context (long-lived listener in the bot
# process, see progress_listener.py) — explicit locale only (bug #10).
# $percent — an integer (0-100).
progress-downloading = ⏳ Downloading… { $percent }%
# For streams with no known total_bytes (percent = None): $mb is a
# number, $speed is an already-formatted string like "1.2 MB/s" (same
# pattern as $platforms in help-text).
progress-downloading-nostream = ⏳ Downloaded { $mb } MB ({ $speed })
# Day 11B.1 — the download→postprocess boundary, audio path (mp3) only.
# No percentage: transcode-itself progress is out of scope.
progress-converting = ⏳ Converting to MP3…
# Day 11D-2 — the card's last states. Short on purpose: the failure
# reason arrives as a separate message.
progress-uploading = ⏳ Sending the file…
progress-done = ✅ Sent
progress-failed = ❌ Failed

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
health-fail = ❌ Unavailable
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
