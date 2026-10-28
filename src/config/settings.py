"""Application configuration.

All settings are loaded from environment variables (via .env in local dev).
This is the single source of truth for configuration — no config values
should be hardcoded anywhere else in the codebase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Root application settings.

    Grouped flat for now (Day 1). If this grows too large in later phases,
    split into nested settings groups (BotSettings, DatabaseSettings, ...).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment ---
    environment: str = Field(default="local", description="local | staging | production")
    log_level: str = Field(default="INFO")

    # --- Observability (ADR 0006) ---
    # Directory for the rotating JSON log file `<service>.log` (bot.log,
    # worker.log), in addition to stdout. Unset = stdout only. In Docker
    # it is a named volume (docker-compose.yml), so `down`/`up -d` keep it.
    log_dir: Path | None = Field(default=None)
    log_file_max_mb: int = Field(default=50, gt=0)
    log_file_backups: int = Field(default=10, ge=1)
    # Sentry is off unless a DSN is set. Errors only, no tracing, no PII.
    sentry_dsn: SecretStr | None = Field(default=None)

    # --- Telegram ---
    bot_token: SecretStr = Field(..., description="Telegram Bot API token from @BotFather")

    # --- Telegram local Bot API server (Day 6) ---
    # `telegram_api_id`/`telegram_api_hash` are consumed by the
    # `telegram-bot-api` container itself (via docker-compose env), not
    # by our Python code directly — kept here anyway so that
    # USE_LOCAL_BOT_API=true without them fails validation at startup
    # (`_local_bot_api_needs_credentials`) rather than as an obscure
    # runtime error from the bot-api server. Free credentials from
    # my.telegram.org — an application registration, not a paid API tier.
    telegram_api_id: int | None = Field(default=None)
    telegram_api_hash: SecretStr | None = Field(default=None)
    use_local_bot_api: bool = Field(
        default=False,
        description="If True, bot/worker connect to a local Bot API server "
        "instead of api.telegram.org — raises the file upload limit from "
        "50MB to 2000MB. Requires telegram_api_id/telegram_api_hash.",
    )
    local_bot_api_base_url: str = Field(default="http://telegram-bot-api:8081")

    # --- i18n (Day 9) ---
    # Last-resort locale when the user has neither an override nor a
    # recognised Telegram language_code. It lives here because it is the
    # only configurable part of localization; SUPPORTED_LOCALES is code
    # anyway (a new locale needs FTL files and button translations).
    default_locale: str = Field(default="en")

    # --- Download flow (Day 7) ---
    # Domain allowlist (SECURITY.md). Suffix match per label, so
    # "youtube.com" also covers www./m. subdomains. Empty list = allow
    # every site yt-dlp supports (dev escape hatch only). Override via
    # env: ALLOWED_DOMAINS='["youtube.com","tiktok.com"]'
    allowed_domains: list[str] = Field(
        default=[
            "youtube.com",
            "youtu.be",
            "tiktok.com",
            "instagram.com",
            "twitter.com",
            "x.com",
            "vk.com",
        ]
    )
    # Exceptions to the allowlist, same suffix match, checked first. For
    # subdomains the allowlist admits but nothing downstream can tell
    # apart: YouTube Music is extracted as plain "youtube", so the
    # per-extractor DISABLED_FORMATS can't exclude it. Override via env:
    # BLOCKED_DOMAINS='["music.youtube.com"]'
    blocked_domains: list[str] = Field(default=["music.youtube.com"])
    # How long a shown preview stays actionable (the ✅ button under it).
    # After the TTL the stored URL expires in Redis and the button
    # politely reports that the preview is stale.
    preview_context_ttl_seconds: int = Field(default=600)
    # Day 11C (v2): per-source format kill-switch (FormatPolicy). Keyed by
    # lowercased yt-dlp extractor_key; a listed kind is hidden on the
    # preview card AND refused by RequestDownloadUseCase. Empty = all
    # formats everywhere. Override via env:
    # DISABLED_FORMATS='{"youtube": ["audio"]}'
    disabled_formats: dict[str, list[Literal["video", "audio"]]] = Field(default_factory=dict)

    # --- Access control ---
    # Telegram user ids allowed to run operational commands (/health,
    # /worker_ping, /worker_status). Empty = nobody: fail closed, so a
    # fresh deployment never exposes diagnostics to the public.
    # Override via env: ADMIN_TELEGRAM_IDS='[123456789]'
    admin_telegram_ids: list[int] = Field(default_factory=list)

    # --- Rate limiting (Day 8) ---
    # Downloads are the expensive action (worker CPU, bandwidth, disk),
    # previews are cheaper but still hit yt-dlp extraction — both are
    # limited, chat messages themselves are not. Sliding windows,
    # enforced per telegram user id at the Presentation boundary.
    rate_limit_downloads_per_hour: int = Field(default=10)
    rate_limit_previews_per_minute: int = Field(default=5)

    # --- File delivery (Day 8.1 hotfix) ---
    # Request timeout specifically for uploading the downloaded file to
    # Telegram. aiogram's default per-request timeout is 60s — a ~1GB
    # upload to the local Bot API server takes longer, the client gives
    # up while the server keeps processing, and the user gets an error
    # followed by the file anyway (false negative, seen 2026-07-05).
    # 1800s covers the worst case (2GB on a slow disk); a genuinely
    # stuck job is still killed by the arq job timeout, so this long
    # timeout cannot hang the worker forever.
    file_upload_timeout_seconds: int = Field(default=1800)

    # Hard ceiling for one download job (was a hardcoded constant in
    # ProcessDownloadUseCase — moved here Day 8.2). With retries now
    # enabled in yt-dlp, a 1-2GB video on a throttled CDN can
    # legitimately take >10 min; a genuinely stuck process is still
    # terminate()'d by YtDlpDownloader when this expires.
    download_timeout_seconds: int = Field(default=1800)

    # Overall ceiling for one preview extraction (bot side; /download
    # goes through the preview too). yt-dlp's own socket_timeout/retries
    # bound each request, not the whole extraction, so a stalled source
    # could hold an executor thread indefinitely. The extraction runs in
    # a child process that is terminate()'d when this expires.
    preview_timeout_seconds: int = Field(default=60, gt=0)

    # Stale-request reaper (ADR 0004): a pending/processing request whose
    # last update is older than the worker's job_timeout plus this grace
    # is failed and its user notified. The grace absorbs clock skew and
    # the tail of a job arq is cancelling at job_timeout.
    stale_request_grace_seconds: int = Field(default=300, gt=0)

    # Disk guard (ADR 0005): a download is refused (error-storage-full)
    # when less than this is free in the download directory. A video+audio
    # download holds both streams and the merged file at once (~2x the
    # file), and the worker runs several jobs side by side, so keep this
    # at a few times max_deliverable_file_size_mb. 0 disables the check.
    download_min_free_disk_mb: int = Field(default=3072, ge=0)

    # Single source of truth for the deliverable file size limit — was
    # previously duplicated as a hardcoded constant in both
    # TelegramNotifier and ProcessDownloadUseCase (a real DRY violation
    # flagged during Day 5 review). Both now receive this via DI instead.
    max_deliverable_file_size_mb: int = Field(default=50)

    # --- PostgreSQL ---
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="umd")
    postgres_user: str = Field(default="umd")
    postgres_password: SecretStr = Field(default=SecretStr("umd"))

    # --- Redis ---
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)

    @property
    def postgres_dsn(self) -> str:
        """DSN for asyncpg (raw driver, used for health checks in Day 1).

        Note: from Day 2 onward, SQLAlchemy will use its own async DSN
        (postgresql+asyncpg://...) built the same way — this property will
        be reused/extended, not replaced.
        """
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sqlalchemy_dsn(self) -> str:
        """DSN for SQLAlchemy's async engine — same components as postgres_dsn,
        just with the +asyncpg dialect prefix SQLAlchemy requires.
        """
        return self.postgres_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

    @field_validator("sentry_dsn", "log_dir", "telegram_api_id", "telegram_api_hash", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # `SENTRY_DSN=` / `LOG_DIR=` / `TELEGRAM_API_ID=` in .env (as in
        # .env.example) mean "not set", not an empty DSN, the current
        # directory or an unparsable integer.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _local_bot_api_needs_credentials(self) -> Settings:
        if not self.use_local_bot_api:
            return self
        missing = [
            name
            for name, value in (
                ("TELEGRAM_API_ID", self.telegram_api_id),
                ("TELEGRAM_API_HASH", self.telegram_api_hash),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"USE_LOCAL_BOT_API=true requires {' and '.join(missing)}: the local "
                "telegram-bot-api server logs in to Telegram with this application "
                "id/hash (free, https://my.telegram.org/apps; not the bot token). "
                "Set them, or set USE_LOCAL_BOT_API=false (50 MB upload limit)."
            )
        return self

    @field_validator("disabled_formats")
    @classmethod
    def _lowercase_extractor_keys(
        cls, value: dict[str, list[Literal["video", "audio"]]]
    ) -> dict[str, list[Literal["video", "audio"]]]:
        return {key.lower(): kinds for key, kinds in value.items()}

    @property
    def redis_dsn(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def allowed_domains_set(self) -> frozenset[str]:
        return frozenset(self.allowed_domains)

    @property
    def blocked_domains_set(self) -> frozenset[str]:
        return frozenset(self.blocked_domains)

    @property
    def admin_telegram_ids_set(self) -> frozenset[int]:
        return frozenset(self.admin_telegram_ids)

    @property
    def log_file_max_bytes(self) -> int:
        return self.log_file_max_mb * 1024 * 1024

    @property
    def download_min_free_disk_bytes(self) -> int:
        return self.download_min_free_disk_mb * 1024 * 1024

    @property
    def max_deliverable_file_size_bytes(self) -> int:
        return self.max_deliverable_file_size_mb * 1024 * 1024


def get_settings() -> Settings:
    """Factory function, kept separate from a module-level singleton.

    Using a factory (instead of `settings = Settings()` at import time)
    makes testing easier — tests can construct Settings with overrides
    without relying on environment variables being set at import time.
    """
    return Settings()  # type: ignore[call-arg]  # fields are populated from env, not call args
