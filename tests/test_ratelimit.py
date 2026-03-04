"""Tests for src.ratelimit — Token bucket rate limiting."""

from __future__ import annotations

import time

from src.ratelimit import RateLimiter, _TokenBucket

# ===== _TokenBucket =====


class TestTokenBucket:
    def test_consume_succeeds_when_tokens_available(self):
        bucket = _TokenBucket(capacity=10, refill_rate=1.0)
        assert bucket.consume() is True

    def test_consume_fails_when_empty(self):
        bucket = _TokenBucket(capacity=2, refill_rate=0.0)
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is False

    def test_refills_over_time(self):
        bucket = _TokenBucket(capacity=2, refill_rate=100.0)  # fast refill
        bucket.consume()
        bucket.consume()
        # With a high refill rate, after a tiny delay tokens should refill
        time.sleep(0.05)
        assert bucket.consume() is True

    def test_does_not_exceed_capacity(self):
        bucket = _TokenBucket(capacity=3, refill_rate=1000.0)
        time.sleep(0.01)
        # Should cap at capacity even with high refill
        count = 0
        for _ in range(10):
            if bucket.consume():
                count += 1
        assert count <= 3

    def test_consume_multiple_tokens(self):
        bucket = _TokenBucket(capacity=5, refill_rate=0.0)
        assert bucket.consume(3) is True
        assert bucket.consume(3) is False  # only 2 left
        assert bucket.consume(2) is True


# ===== RateLimiter =====


class TestRateLimiter:
    def test_check_allows_requests(self):
        limiter = RateLimiter(capacity=10, refill_rate=1.0)
        assert limiter.check("user-1") is True

    def test_per_user_isolation(self):
        limiter = RateLimiter(capacity=2, refill_rate=0.0)
        assert limiter.check("user-1") is True
        assert limiter.check("user-1") is True
        assert limiter.check("user-1") is False  # exhausted for user-1
        assert limiter.check("user-2") is True  # user-2 has own bucket

    def test_rate_limits_exhausted_user(self):
        limiter = RateLimiter(capacity=1, refill_rate=0.0)
        assert limiter.check("user-1") is True
        assert limiter.check("user-1") is False

    def test_global_instances_exist(self):
        from src.ratelimit import embedding_limiter, tool_limiter

        assert isinstance(tool_limiter, RateLimiter)
        assert isinstance(embedding_limiter, RateLimiter)
        assert tool_limiter.capacity == 60
        assert embedding_limiter.capacity == 30
