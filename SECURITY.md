# Security

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's
private vulnerability reporting for this repository (Security tab →
"Report a vulnerability"), or contact the maintainer through the profile
linked in the README. Include what you found, how to reproduce it and what
an attacker could do with it. Expect an acknowledgement within a week.

This is a personal project without a bug bounty.

## Threat model in brief

The bot accepts arbitrary text from any Telegram user, passes URLs to
yt-dlp, which fetches content from third-party servers, and stores
requests in PostgreSQL. The main risks are: using the bot to fetch from
arbitrary hosts, malformed input reaching the downloader or the database,
leaking secrets or diagnostics to users, and exhausting the host's disk,
CPU or bandwidth.

## Untrusted input

**URLs.** Every link is validated at the presentation boundary, before
the rate limiter and before yt-dlp sees it
(`src/domain/value_objects/url_validation.py`):

- the scheme must be `http` or `https` and the host must be present;
- the host must match the **domain allowlist** (`ALLOWED_DOMAINS`), an
  allowlist rather than a blocklist. Matching is per label:
  `youtube.com` admits `www.youtube.com`, not `evilyoutube.com`, and an
  allowed domain in the path does not count;
- `BLOCKED_DOMAINS` carves exceptions out of the allowlist and wins over
  it (default: `music.youtube.com`, which yt-dlp extracts as plain YouTube);
- the use case re-validates the structure as a safety net.

An empty allowlist means "allow every site yt-dlp supports". It exists
for local development only; never deploy with it.

**Callback data** is client-supplied and can be forged. It carries only a
random token; the URL and extractor key come from the stored
`PreviewContext`, and `FormatPolicy` is enforced again in
`RequestDownloadUseCase`.

**Text from source sites** (titles, uploader names) is HTML-escaped before
it is put into a message, because the bot's parse mode is HTML.

**The database** is treated as untrusted on read: unreadable values degrade
to a truthful default or raise a domain error, never a crash after the user
was told "accepted" (docs/architecture.md, "The database is untrusted
input").

## Process and file handling

- yt-dlp runs through its Python API, not a CLI. The only subprocess the
  application starts itself is `ffprobe`, with an argument list (no
  shell) and a timeout.
- Extraction and download run in child processes that are killed on
  timeout, so a hostile or stalled source cannot hold the bot or worker.
- Files are written as `<request_dir>/<video id>.<ext>` with
  `restrictfilenames`; the user-visible file name is sanitized separately
  (`delivery_filename`) and never used as a path.
- Downloads above the configured size are refused before they start, the
  disk guard refuses downloads when free space is low, and per-user rate
  limits apply to previews and downloads.
- Containers run as an unprivileged user (uid 10001). PostgreSQL and Redis
  are published on `127.0.0.1` only; nothing listens on a public port, as
  the bot uses long polling.

## Secrets

- All secrets come from the environment (`.env`, never committed;
  `.env.example` holds placeholders only). `BOT_TOKEN`,
  `TELEGRAM_API_HASH`, `POSTGRES_PASSWORD` and `SENTRY_DSN` are
  `SecretStr` and are not printed by the settings object.
- Change the default PostgreSQL password before deploying anywhere but a
  laptop.
- Sentry is opt-in and sends no frame locals (they can hold tokens and
  URLs) and no PII.
- Operational commands (`/health`, `/worker_ping`, `/worker_status`) are
  limited to `ADMIN_TELEGRAM_IDS`; the default is nobody.
- Cookies or account credentials for source sites are deliberately not
  supported. Using an account to download is a separate decision with its
  own risks (the account can be banned, and its session would live on the
  server).

## Responsible use

This project is a technical exercise in building a reliable media pipeline.
It does not grant any right to the content it downloads.

- Download only content you own, content licensed for downloading, or
  content you are otherwise permitted to copy under the law that applies to
  you.
- Platform terms of service (YouTube, TikTok, Instagram, X, VK and others)
  may prohibit downloading; running this bot against them is your decision
  and your responsibility.
- The domain allowlist, rate limits and size limits exist to keep the bot a
  personal tool rather than a public mirror. Do not run an open instance
  for the general public without your own legal review.
