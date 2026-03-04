"""Simple in-memory rate limiter using token bucket algorithm."""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class _TokenBucket:
    capacity: int
    refill_rate: float  # tokens per second
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def consume(self, n: int = 1) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


class RateLimiter:
    """Per-user rate limiter with configurable capacity, refill rate, and max entries.

    Uses an OrderedDict with LRU eviction to prevent unbounded memory growth (F-06).
    """

    def __init__(
        self, capacity: int = 60, refill_rate: float = 1.0, max_buckets: int = 10_000
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_buckets = max_buckets
        self._buckets: OrderedDict[str, _TokenBucket] = OrderedDict()

    def check(self, user_id: str) -> bool:
        """Returns True if the request is allowed, False if rate limited."""
        if user_id in self._buckets:
            # Move to end (most recently used)
            self._buckets.move_to_end(user_id)
        else:
            # Evict oldest entry if at capacity
            if len(self._buckets) >= self.max_buckets:
                self._buckets.popitem(last=False)
            self._buckets[user_id] = _TokenBucket(
                capacity=self.capacity, refill_rate=self.refill_rate
            )

        return self._buckets[user_id].consume()


# Global instances
tool_limiter = RateLimiter(capacity=60, refill_rate=1.0)  # 60 req/min sustained
embedding_limiter = RateLimiter(capacity=30, refill_rate=0.5)  # 30 embeds/min
