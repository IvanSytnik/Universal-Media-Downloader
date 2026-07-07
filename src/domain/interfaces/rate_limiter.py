"""Rate limiter interface. Domain layer — no implementation here.

The port is deliberately client-agnostic: the same limiter will guard
the REST API in Phase 5 (different key namespace, same contract).
`limit` and `window_seconds` are call arguments, not limiter state —
that's the pre-laid hook for per-tier limits (Premium, Phase 4) without
implementing tiers now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Outcome of a rate-limit check.

    `retry_after_seconds` is meaningful only when `allowed` is False:
    it tells the caller how long until the oldest event leaves the
    sliding window (i.e. when the next attempt could succeed).
    """

    allowed: bool
    retry_after_seconds: int = 0


class RateLimiterPort(Protocol):
    async def acquire(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Try to consume one slot for `key` within a sliding window.

        Returns RateLimitResult(allowed=True) and records the event if
        the caller is under `limit` events per `window_seconds`;
        otherwise returns allowed=False with a retry hint and records
        nothing (denied attempts must not extend the lockout).
        """
        ...
