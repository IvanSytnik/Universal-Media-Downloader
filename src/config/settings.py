"""Application configuration.

All settings are loaded from environment variables (via .env in local dev).
This is the single source of truth for configuration — no config values
should be hardcoded anywhere else in the codebase.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
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

    # --- Telegram ---
    bot_token: SecretStr = Field(..., description="Telegram Bot API token from @BotFather")

    # --- Telegram local Bot API server (Day 6) ---
    # `telegram_api_id`/`telegram_api_hash` are consumed by the
    # `telegram-bot-api` container itself (via docker-compose env), not
    # by our Python code directly — kept here anyway so misconfiguration
    # fails validation at startup rather than as an obscure runtime error
    # from the bot-api server. Free credentials from my.telegram.org —
    # this is an application registration, not a paid API tier.
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
    # Последний fallback локали, когда у юзера нет ни override, ни
    # распознаваемого Telegram language_code. Держим тут, т.к.
    # SUPPORTED_LOCALES всё равно код (новые FTL + переводы кнопок), а
    # это — единственный конфигурируемый параметр локализации.
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
    # How long a shown preview stays actionable (the ✅ button under it).
    # After the TTL the stored URL expires in Redis and the button
    # politely reports that the preview is stale.
    preview_context_ttl_seconds: int = Field(default=600)

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

    @property
    def redis_dsn(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def allowed_domains_set(self) -> frozenset[str]:
        return frozenset(self.allowed_domains)

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
 