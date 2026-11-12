# Deployment runbook

How to run Universal Media Downloader on a single Linux server with
Docker Compose. Provider-neutral: any VPS with Ubuntu LTS works the same
way. Status: written and checked against a local Docker stack; it has not
been executed on a server yet, and the resource figures below are
estimates until they are measured there.

## 1. What runs

| Service | Image | Role |
|---|---|---|
| `postgres` | `postgres:16-alpine` | requests and users |
| `redis` | `redis:7-alpine` | job queue, FSM state, preview tokens, progress pub/sub |
| `migrate` | project image | one-shot `alembic upgrade head`; `bot` and `worker` start after it succeeds |
| `bot` | project image | aiogram long polling, previews |
| `worker` | project image | arq; one child process per download (yt-dlp, deno, ffmpeg) |
| `telegram-bot-api` | `aiogram/telegram-bot-api:10.2` (pinned by digest) | local Bot API server, only in the `local-bot-api` profile |

Nothing listens on a public port: the bot polls Telegram, PostgreSQL and
Redis are published on `127.0.0.1` only. All images are available for
`amd64` and `arm64`.

## 2. Sizing

Concurrency is `WORKER_MAX_JOBS` (default 4). Per concurrent download,
**estimated** (to be replaced by figures measured on the target server):

- RAM: about 250–400 MB (a `spawn`ed Python process with yt-dlp, deno for YouTube's JS challenge, ffmpeg for the merge or MP3).
- Disk: about twice the file while video and audio are merged (a 1080p YouTube video is typically 300–700 MB; the hard cap is `MAX_DELIVERABLE_FILE_SIZE_MB`, 2000 MB in the full profile). The Bot API server holds another temporary copy during the upload; the disk guard does not see that one.
- CPU: merging is a remux (cheap); MP3 transcoding uses about one core briefly.
- Traffic: every delivery is downloaded from the source's CDN and uploaded to Telegram, so roughly twice the file size.

Starting point for `WORKER_MAX_JOBS=4`: 4 vCPU, 8 GB RAM, 80 GB disk.
Set `DOWNLOAD_MIN_FREE_DISK_MB` to about 2 × typical file × jobs plus
headroom; the default 3072 suits one or two concurrent 1080p downloads.

**Measured:** none yet. Record here, with the date, `docker stats` peaks
for the worker at 1, 2 and 4 parallel 1080p downloads and the disk peak.

## 3. Provider

TBD after provider evaluation.

Whatever the provider, test the server's IP before committing to it:
YouTube and other sites block many datacenter ranges ("Sign in to confirm
you're not a bot", HTTP 403). Precondition for the test: the image must
solve YouTube's JS challenge, or missing formats look like a block.

```bash
docker compose run --rm --no-deps --entrypoint yt-dlp worker \
  -v --simulate "https://www.youtube.com/watch?v=aqz-KE-bpKQ" 2>&1 \
  | grep -iE "jsc|n challenge|Failed to load player"
```

Expect `Using challenge solver ... (source: python package)` and no
`n challenge solving failed` or `Failed to load player`. A
`Failed to load player ... Read timed out` is a network failure, not a
block; repeat before drawing conclusions.

## 4. Host setup

```bash
# as root on a fresh Ubuntu LTS
adduser --disabled-password umd && usermod -aG sudo umd
# install your SSH key for umd, then in /etc/ssh/sshd_config:
#   PasswordAuthentication no
#   PermitRootLogin no
systemctl restart ssh
apt-get update && apt-get install -y unattended-upgrades vnstat age
# Docker Engine and the Compose plugin: https://docs.docker.com/engine/install/ubuntu/
usermod -aG docker umd
```

**Firewall: inbound SSH only.**

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp          # better: ufw allow from <your IP> to any port 22
ufw enable
```

Docker publishes ports past `ufw`. That is safe here because compose
binds PostgreSQL and Redis to `127.0.0.1`; do not change those bindings
to `0.0.0.0`. If the provider offers a network firewall, apply the same
rule there too.

## 5. First deployment

```bash
git clone https://github.com/IvanSytnik/Universal-Media-Downloader.git umd
cd umd && git checkout v1.2.0
cp .env.example .env && chmod 600 .env
```

Fill in `.env` for the **full** profile:

- `BOT_TOKEN`
- `USE_LOCAL_BOT_API=true` **and** `COMPOSE_PROFILES=local-bot-api` (both or neither)
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
- `MAX_DELIVERABLE_FILE_SIZE_MB=2000`. With the default 50, 720p and 1080p videos download and are then refused as too large.
- `POSTGRES_PASSWORD`: a new random value. PostgreSQL applies it only when the data volume is first created; changing it later needs `ALTER USER` as well.
- `ADMIN_TELEGRAM_IDS`, `WORKER_MAX_JOBS`, `DOWNLOAD_MIN_FREE_DISK_MB`, optionally `SENTRY_DSN`

If the bot is moving here from another server, follow section 6 first.
Then:

```bash
docker compose up -d --build
docker compose ps                 # migrate: Exited (0); others Up; worker healthy
```

## 6. Moving the bot between Bot API servers

A bot token is logged in to one Bot API server at a time. Never run two
stacks with the same token: two pollers get `409 Conflict`, and two
local servers compete for the same bot.

**Bot currently on the cloud API** (a new bot, or the minimal profile):
log it out once before its first start on a local server. It cannot use
the cloud API again for 10 minutes.

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/logOut"     # {"ok":true,"result":true}
```

**Bot currently on another local server** (moving from the old host to
this one), in this order:

1. On the old host, release the bot from the old local server. The call runs from the `bot` container, so the token comes from its settings and stays out of the shell history:

   ```bash
   docker compose exec bot python -c "
   import json, urllib.request
   from src.config.settings import Settings
   s = Settings()
   url = f'{s.local_bot_api_base_url}/bot{s.bot_token.get_secret_value()}/close'
   print(json.load(urllib.request.urlopen(url)))"
   ```

   `close` refuses during the first 10 minutes after the server started.
2. Stop the old stack: `docker compose down` (keep the volumes until the move is verified).
3. Move the data (next block), then start this host (section 5).

Do not send requests to `api.telegram.org` with a token that runs on a
local server: a cloud call can log the bot back in to the cloud.

**Moving the data:**

```bash
# old host
docker compose up -d postgres
docker compose exec -T postgres pg_dump -U umd -Fc umd > umd.dump
# new host, before the first `up` of bot and worker
docker compose up -d postgres
docker compose exec -T postgres pg_restore -U umd -d umd --clean --if-exists < umd.dump
docker compose up -d --build      # migrate brings the schema to head
```

## 7. Checks after every deployment

- `docker compose ps`: `migrate` exited with 0, `worker` is healthy, `telegram-bot-api` has not restarted (`docker inspect -f '{{.RestartCount}}' <container>`).
- Send a link: preview card, 1080p download, video arrives as a player, the card ends in "✅ Sent".
- `docker compose exec worker tail -n 50 /var/log/umd/worker.log`: `notifier_file_sent method=video`, then within 5 minutes a tick of `reap_stale_requests_job` and `cleanup_expired_downloads_job`.
- `docker compose exec worker ls /tmp/umd-downloads` is empty after delivery.
- `grep -c "n challenge solving failed" /var/log/umd/worker.log` inside the worker is 0.
- On the first deployment over existing data: the first reaper tick fails requests that were left pending; their users get `error-request-stale`, possibly about an old request.

## 8. Upgrades and rollback

```bash
git fetch --tags && git checkout vX.Y.Z
docker compose up -d --build      # migrate runs first, then bot and worker
```

- Upgrade `bot` and `worker` together: they share code and job payloads.
- If the release notes say the job payload changed, let the queue drain first (`/worker_status`, or wait until no request is `processing`), then upgrade.
- Rollback: check out the previous tag and rebuild. Downgrading a migration is a separate, manual step (`docker compose run --rm migrate alembic downgrade <rev>`); some are lossy, for example `0005` turns `best` into `hd_720`. Restore from a backup when in doubt.

## 9. Updating yt-dlp

Versions are pinned by `uv.lock`; the image installs exactly them. Sites
change faster than releases, so yt-dlp is the dependency that needs
updates most often. `yt-dlp-ejs` must match the yt-dlp release.

```bash
# in a working copy, not on the server
uv lock --upgrade-package yt-dlp --upgrade-package yt-dlp-ejs
uv sync --locked --extra dev && uv run pytest
git commit -m "build(deps): update yt-dlp" uv.lock   # PR → CI → tag
# on the server
git checkout <new tag> && docker compose up -d --build
```

Then repeat the JS-challenge check from section 3. A bot such as Renovate
or Dependabot can open the lock update automatically.

## 10. Backups

Daily logical dump, encrypted, stored off the host:

```bash
# /home/umd/backup.sh, run from cron: 30 3 * * * /home/umd/backup.sh
set -euo pipefail
cd /home/umd/umd
stamp=$(date -u +%Y%m%dT%H%MZ)
docker compose exec -T postgres pg_dump -U umd -Fc umd \
  | age -r "<age public key>" > "/home/umd/backups/umd-$stamp.dump.age"
find /home/umd/backups -name 'umd-*.dump.age' -mtime +14 -delete
# then copy the new file off the host (object storage or another machine)
```

Keep the age private key off the server. Test a restore into a scratch
database once a month: a backup that was never restored is not a backup.
Logs (`app_logs`) and downloads are not backed up; the Bot API volume
(`telegram_bot_api_data`) holds only the server's session, which is
recreated by logging in again.

## 11. Day-to-day

- Logs: `docker compose exec bot tail -f /var/log/umd/bot.log` (JSON, rotated: `LOG_FILE_MAX_MB` × `LOG_FILE_BACKUPS`).
- Traffic: `vnstat -m`. Some providers throttle "excessive" use without a stated threshold; watch the monthly volume from day one.
- Disk: `df -h` and the worker's `storage_low_disk_space` warnings.
- Errors: Sentry, if `SENTRY_DSN` is set.

## 12. Towards CI/CD

Not set up yet. The intended path: CI builds the image from `uv.lock` and
pushes it to a registry; a deploy job behind a protected environment
connects over SSH, pulls, and runs `docker compose up -d`; `migrate`
applies the schema before `bot` and `worker` start, and both are always
deployed together.
