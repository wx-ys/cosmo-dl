"""Tests for RateLimiter."""
import time
import pytest
from cosmo_dl.engine.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_parse_rate_bytes(self):
        limiter = RateLimiter("1M")
        assert limiter._rate_bytes == 1_000_000

    def test_parse_rate_kilobytes(self):
        limiter = RateLimiter("500K")
        assert limiter._rate_bytes == 500_000

    def test_parse_unlimited(self):
        limiter = RateLimiter("unlimited")
        assert limiter._rate_bytes == float("inf")

    def test_parse_bare_number(self):
        limiter = RateLimiter("1000000")
        assert limiter._rate_bytes == 1_000_000

    def test_acquire_within_limit_returns_zero(self):
        limiter = RateLimiter("10M")
        wait = limiter.acquire(1000)
        assert wait == 0.0

    def test_acquire_exceeding_limit_returns_wait_time(self):
        limiter = RateLimiter("1M")
        # Acquire 2MB worth of tokens → should need to wait for ~1 second
        wait = limiter.acquire(2_000_000)
        # Should need to wait roughly 1 second to get back under the limit
        assert 0.9 <= wait <= 2.1

    def test_acquire_infinite_rate(self):
        limiter = RateLimiter("unlimited")
        wait = limiter.acquire(10_000_000_000)
        assert wait == 0.0

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError, match="Invalid rate format"):
            RateLimiter("abc")
