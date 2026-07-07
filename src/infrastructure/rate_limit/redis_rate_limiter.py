"""Redis implementation of RateLimiterPort — sliding window over a ZSET.

Why sliding window and not fixed INCR+EXPIRE: a fixed window allows up
to 2× the limit around a window boundary (N requests at 59s + N at 61s).
The ZSET variant is exact: each event is a member scored with its
timestamp; the window is "now - window_seconds .. now".

Concurrency note: the check (ZCARD) and the record (ZADD) are two
Redis commands, so two truly simultaneous requests from one user could
both pass at exactly the limit boundary. For per-user Telegram traffic
this race is practically unreachable and its worst case is one extra
event — an acceptable trade-off versus shipping a Lua script for
atomicity. If REST API traffic (Phase 5) makes it matter, the fix is a
small EVAL, behind the same port, with no caller changes.

Denied attempts are NOT recorded (see port docstring): hammering a
locked-out limiter must not push the unlock time further away.
"""

from __future__ import annotations

import time
import uuid

from redis.asyncio import Redis

from src.domain.interfaces.rate_limiter import RateLimitResult

_KEY_PREFIX = "umd:ratelimit:"


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def acquire(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        redis_key = _KEY_PREFIX + key
        now = time.time()
        window_start = now - window_seconds

        # Prune expired events, then count what's left in the window.
        # Pipelined to save a round trip; atomicity is not required for
        # correctness here (see module docstring).
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(redis_key, "-inf", window_start)
            pipe.zcard(redis_key)
            _, current_count = await pipe.execute()

        if int(current_count) >= limit:
            oldest = await self._redis.zrange(redis_key, 0, 0, withscores=True)
            if oldest:
                oldest_score = float(oldest[0][1])
                retry_after = max(1, int(oldest_score + window_seconds - now) + 1)
            else:
                # Window emptied between the two commands — extremely
                # unlikely, but never return a misleading long wait.
                retry_after = 1
            return RateLimitResult(allowed=False, retry_after_seconds=retry_after)

        async with self._redis.pipeline(transaction=True) as pipe:
            # uuid member: two events in the same clock tick must not
            # collapse into one ZSET entry.
            pipe.zadd(redis_key, {uuid.uuid4().hex: now})
            # Safety-net TTL so abandoned keys don't live forever; +60s
            # margin keeps the TTL from expiring a still-relevant window.
            pipe.expire(redis_key, window_seconds + 60)
            await pipe.execute()

        return RateLimitResult(allowed=True)
