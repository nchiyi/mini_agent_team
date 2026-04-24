import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Token-bucket per-user rate limiter with a global concurrency semaphore."""

    def __init__(
        self,
        per_user_per_minute: int = 10,
        burst: int = 3,
        max_concurrent: int = 5,
        enabled: bool = True,
    ):
        self._rate = per_user_per_minute / 60.0
        self._burst = float(burst)
        self._buckets: dict[int, _Bucket] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._enabled = enabled

    def check(self, user_id: int) -> bool:
        """Return True if the request is allowed; False if rate-limited."""
        if not self._enabled:
            return True
        bucket = self._buckets.setdefault(user_id, _Bucket(tokens=self._burst))
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate)
        bucket.last_refill = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore

    @property
    def enabled(self) -> bool:
        return self._enabled
