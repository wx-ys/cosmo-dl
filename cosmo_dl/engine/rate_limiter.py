"""Token bucket rate limiter for download bandwidth throttling."""

import re
import threading
import time


class RateLimiter:
    """Token bucket algorithm for bandwidth rate limiting.

    Parameters
    ----------
    rate : str
        Rate specification, e.g. "10M" (10 MB/s), "500K" (500 KB/s),
        "unlimited", or bare number like "1000000" (bytes/s).
    """

    def __init__(self, rate: str) -> None:
        self._rate_bytes = self._parse_rate(rate)
        # tokens represent bytes allowed
        self._tokens: float = self._rate_bytes
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    @staticmethod
    def _parse_rate(rate: str) -> float:
        """Parse a rate string into bytes per second."""
        rate = rate.strip().lower()
        if rate in ("unlimited", "0", "none"):
            return float("inf")

        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmg]?)(?:b/s)?", rate)
        if not match:
            raise ValueError(
                f"Invalid rate format: {rate!r}. Expected e.g. '10M', '500K', '1G', 'unlimited'"
            )

        value = float(match.group(1))
        suffix = match.group(2)

        multipliers = {"": 1, "k": 1_000, "m": 1_000_000, "g": 1_000_000_000}
        return value * multipliers[suffix]

    def acquire(self, bytes_count: int) -> float:
        """Request permission to transfer `bytes_count` bytes.

        Returns
        -------
        float
            Seconds to wait before proceeding. 0.0 means proceed immediately.
        """
        if self._rate_bytes == float("inf"):
            return 0.0

        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill

            # Refill tokens based on elapsed time
            self._tokens = min(
                self._rate_bytes,
                self._tokens + elapsed * self._rate_bytes,
            )
            self._last_refill = now

            # If we have enough tokens, consume and proceed
            if self._tokens >= bytes_count:
                self._tokens -= bytes_count
                return 0.0

            # Not enough tokens — calculate wait time
            deficit = bytes_count - self._tokens
            wait = deficit / self._rate_bytes

            # Fast-forward: consume the tokens we do have, and the rest will
            # be "paid" by waiting
            self._tokens = 0.0

            return wait
