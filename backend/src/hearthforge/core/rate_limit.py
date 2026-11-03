"""In-memory token buckets (single instance, D-023)."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, clock: callable = time.monotonic) -> None:  # type: ignore[valid-type]
        self._buckets: dict[str, _Bucket] = {}
        self._clock = clock
        self._ops = 0

    def hit(self, key: str, per_minute: int, cost: float = 1.0) -> bool:
        """Consume `cost` tokens from `key`'s bucket (capacity = per_minute). False if empty."""
        now = self._clock()
        rate = per_minute / 60.0
        b = self._buckets.get(key)
        if b is None:
            b = self._buckets[key] = _Bucket(float(per_minute), now)
        else:
            b.tokens = min(per_minute, b.tokens + (now - b.updated) * rate)
            b.updated = now
        self._ops += 1
        if self._ops % 10_000 == 0:
            self._prune(now)
        if b.tokens >= cost:
            b.tokens -= cost
            return True
        return False

    def _prune(self, now: float) -> None:
        stale = [k for k, b in self._buckets.items() if now - b.updated > 600]
        for k in stale:
            del self._buckets[k]

    def reset(self) -> None:
        self._buckets.clear()
