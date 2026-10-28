# syntax=docker/dockerfile:1
#
# One image for both the bot and the worker (same code, different command).
#
# Two stages: the builder resolves Python dependencies into an isolated
# virtualenv; the runtime stage copies only that venv plus the system
# binaries yt-dlp needs, so build tooling (uv, compilers, curl) never
# ships in the final image.

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app
COPY pyproject.toml ./

# Dependencies only, not the project itself: the code runs from /app/src
# via PYTHONPATH, so path-relative lookups (locales_dir() resolves
# parents[3] of src/presentation/telegram/i18n.py) land inside /app.
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python --no-cache -r pyproject.toml

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# ffmpeg is the system binary (NOT the pip package of the same name — a
# common mistake that silently downloads nothing); yt-dlp uses it for the
# MP4 merge and MP3 extraction.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Deno is the JS runtime yt-dlp-ejs needs to decipher YouTube metadata,
# even for extract_info(download=False). Copied from the official image at
# a pinned version instead of piping an install script into sh.
COPY --from=denoland/deno:bin-2.5.6 /deno /usr/local/bin/deno

# Unprivileged runtime user. /tmp/umd-downloads is the worker's download
# directory (DOWNLOAD_STORAGE_DIR) and the mount point of the shared
# download_storage volume; creating it here owned by `app` means a fresh
# named volume inherits that ownership. /var/log/umd is LOG_DIR, the
# mount point of the app_logs volume — same reason (ADR 0006).
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app \
    && mkdir -p /tmp/umd-downloads /var/log/umd \
    && chown app:app /tmp/umd-downloads /var/log/umd

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./
COPY infra/alembic ./infra/alembic
# FTL locales: the bot renders them, the worker localizes error messages.
COPY locales ./locales
COPY src ./src

USER app

# Migrations are not run here: the one-shot `migrate` compose service
# applies them before bot and worker start (docker-compose.yml).
CMD ["python", "-m", "src.main"]
