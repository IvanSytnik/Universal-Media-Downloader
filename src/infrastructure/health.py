"""Raw connectivity health checks for external dependencies.

Talks to Postgres/Redis directly (asyncpg / redis-py) rather than through
the repository layer: the point is to probe the dependency itself, with a
short timeout, independent of the application's connection pools.
"""

from __future__ import annotations

import asyncpg
import redis.asyncio as redis

from src.config.settings import Settings
from src.domain.value_objects.health_report import HealthReport


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


class ConnectivityHealthCheck:
    """``HealthCheckPort`` implementation over the raw probes above."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def check(self) -> HealthReport:
        database_ok, database_error = await check_postgres(self._settings)
        cache_ok, cache_error = await check_redis(self._settings)
        return HealthReport(
            database_ok=database_ok,
            cache_ok=cache_ok,
            database_error=database_error,
            cache_error=cache_error,
        )
