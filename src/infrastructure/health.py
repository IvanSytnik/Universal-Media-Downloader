"""Raw connectivity health checks for external dependencies.

Day 1 note: this talks to Postgres/Redis directly (asyncpg / redis-py),
without going through SQLAlchemy or the repository layer, because neither
exists yet. From Day 2, once SQLAlchemy + repositories land, this module
will be reduced to a thin wrapper that goes through the same connection
pools as the rest of the app — no separate driver.
"""

from __future__ import annotations

from dataclasses import dataclass

import asyncpg
import redis.asyncio as redis

from src.config.settings import Settings


@dataclass(frozen=True, slots=True)
class HealthStatus:
    postgres_ok: bool
    redis_ok: bool
    postgres_error: str | None = None
    redis_error: str | None = None

    @property
    def all_ok(self) -> bool:
        return self.postgres_ok and self.redis_ok


async def check_postgres(settings: Settings) -> tuple[bool, str | None]:
    try:
        conn = await asyncpg.connect(dsn=settings.postgres_dsn, timeout=3)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return True, None
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        return False, str(exc)


async def check_redis(settings: Settings) -> tuple[bool, str | None]:
    client: redis.Redis | None = None
    try:
        client = redis.from_url(  # type: ignore[no-untyped-call]  # untyped in this redis version, pulled in transitively by arq
            settings.redis_dsn, socket_connect_timeout=3
        )
        await client.ping()
        return True, None
    except Exception as exc:  # noqa: BLE001 — health check must never raise
        return False, str(exc)
    finally:
        if client is not None:
            await client.aclose()


async def run_health_check(settings: Settings) -> HealthStatus:
    postgres_ok, postgres_error = await check_postgres(settings)
    redis_ok, redis_error = await check_redis(settings)
    return HealthStatus(
        postgres_ok=postgres_ok,
        redis_ok=redis_ok,
        postgres_error=postgres_error,
        redis_error=redis_error,
    )
