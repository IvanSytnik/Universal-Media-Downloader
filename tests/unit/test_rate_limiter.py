"""RedisRateLimiter — tested against an in-memory fake covering exactly
the Redis surface the limiter uses (ZSET subset + pipeline + expire).
The fake keeps real sorted-set semantics (score-ordered members), so
window pruning and retry_after math are exercised for real; only the
network layer is faked, consistent with test_preview_context_store.py.
"""

from __future__ import annotations

from typing import Any

from src.infrastructure.rate_limit.redis_rate_limiter import RedisRateLimiter


class _FakePipeline:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    async def __aenter__(self) -> _FakePipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def zremrangebyscore(self, key: str, lo: Any, hi: Any) -> None:
        self._ops.append(("zremrangebyscore", (key, lo, hi)))

    def zcard(self, key: str) -> None:
        self._ops.append(("zcard", (key,)))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self._ops.append(("zadd", (key, mapping)))

    def expire(self, key: str, seconds: int) -> None:
        self._ops.append(("expire", (key, seconds)))

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for name, args in self._ops:
            results.append(getattr(self._redis, "_" + name)(*args))
        self._ops.clear()
        return results


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, float]] = {}
        self.last_expire: int | None = None

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self)

    def _zremrangebyscore(self, key: str, lo: Any, hi: Any) -> int:
        zset = self.zsets.get(key, {})
        lo_f = float("-inf") if lo == "-inf" else float(lo)
        removed = [m for m, s in zset.items() if lo_f <= s <= float(hi)]
        for m in removed:
            del zset[m]
        return len(removed)

    def _zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    def _zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.zsets.setdefault(key, {}).update(mapping)
        return len(mapping)

    def _expire(self, key: str, seconds: int) -> bool:
        self.last_expire = seconds
        return True

    async def zrange(
        self, key: str, start: int, stop: int, withscores: bool = False
    ) -> list[tuple[bytes, float]]:
        items = sorted(self.zsets.get(key, {}).items(), key=lambda kv: kv[1])
        sliced = items[start : stop + 1]
        return [(m.encode(), s) for m, s in sliced]


def _limiter(fake: _FakeRedis) -> RedisRateLimiter:
    redis: Any = fake
    return RedisRateLimiter(redis=redis)


async def test_allows_up_to_limit() -> None:
    fake = _FakeRedis()
    limiter = _limiter(fake)
    for _ in range(3):
        result = await limiter.acquire("download:1", limit=3, window_seconds=60)
        assert result.allowed


async def test_denies_over_limit_with_retry_hint() -> None:
    fake = _FakeRedis()
    limiter = _limiter(fake)
    for _ in range(2):
        assert (await limiter.acquire("download:1", limit=2, window_seconds=60)).allowed

    denied = await limiter.acquire("download:1", limit=2, window_seconds=60)
    assert not denied.allowed
    # The window just started, so the wait is ~the full window (+1s margin).
    assert 1 <= denied.retry_after_seconds <= 62


async def test_denied_attempt_is_not_recorded() -> None:
    fake = _FakeRedis()
    limiter = _limiter(fake)
    await limiter.acquire("k", limit=1, window_seconds=60)
    await limiter.acquire("k", limit=1, window_seconds=60)  # denied
    await limiter.acquire("k", limit=1, window_seconds=60)  # denied
    # Only the single allowed event is stored — lockout must not extend.
    assert len(fake.zsets["umd:ratelimit:k"]) == 1


async def test_events_outside_window_are_pruned() -> None:
    fake = _FakeRedis()
    limiter = _limiter(fake)
    # Seed an "old" event manually, far outside any window.
    fake.zsets["umd:ratelimit:k"] = {"old": 1.0}
    result = await limiter.acquire("k", limit=1, window_seconds=60)
    assert result.allowed
    assert "old" not in fake.zsets["umd:ratelimit:k"]


async def test_keys_are_isolated() -> None:
    fake = _FakeRedis()
    limiter = _limiter(fake)
    assert (await limiter.acquire("download:1", limit=1, window_seconds=60)).allowed
    # A different user is unaffected by user 1's exhaustion.
    assert (await limiter.acquire("download:2", limit=1, window_seconds=60)).allowed
    assert not (await limiter.acquire("download:1", limit=1, window_seconds=60)).allowed


async def test_safety_net_ttl_is_set() -> None:
    fake = _FakeRedis()
    await _limiter(fake).acquire("k", limit=5, window_seconds=60)
    assert fake.last_expire == 120  # window + 60s margin
