import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.memory.tier3 import Tier3Store


class BudgetStatus(Enum):
    OK = "ok"
    WARN = "warn"       # usage >= warn_threshold
    EXCEEDED = "exceeded"  # usage >= 100%


@dataclass
class BudgetCheckResult:
    status: BudgetStatus
    used: int
    limit: int
    ratio: float        # used / limit, or 0 if no limit
    period: str         # "daily" | "weekly"

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    @property
    def pct(self) -> float:
        return self.ratio * 100


class TokenBudget:
    """
    Check and record per-user token budgets from tier3 usage logs.

    Config fields (from RateLimitConfig):
        daily_limit   : daily_token_budget (0 = no limit)
        weekly_limit  : weekly_token_budget (0 = no limit)
        warn_threshold: fraction at which to emit a warning (default 0.8)
        hard_stop     : if True refuse dispatch at 100%; if False allow but log
    """

    def __init__(
        self,
        daily_limit: int = 0,
        weekly_limit: int = 0,
        warn_threshold: float = 0.8,
        hard_stop: bool = False,
    ):
        self.daily_limit = daily_limit
        self.weekly_limit = weekly_limit
        self.warn_threshold = warn_threshold
        self.hard_stop = hard_stop

    async def check(
        self,
        *,
        user_id: int,
        tier3: "Tier3Store",
    ) -> list[BudgetCheckResult]:
        """
        Return BudgetCheckResult for each active budget period (daily / weekly).
        An empty list means no budgets are configured.
        """
        from datetime import datetime, timezone, timedelta

        results: list[BudgetCheckResult] = []
        now = datetime.now(timezone.utc)

        if self.daily_limit > 0:
            today_iso = now.strftime("%Y-%m-%d")
            used = await tier3.get_token_usage_since(user_id=user_id, since_iso=today_iso)
            ratio = used / self.daily_limit
            if ratio >= 1.0:
                status = BudgetStatus.EXCEEDED
            elif ratio >= self.warn_threshold:
                status = BudgetStatus.WARN
            else:
                status = BudgetStatus.OK
            results.append(BudgetCheckResult(
                status=status, used=used, limit=self.daily_limit,
                ratio=ratio, period="daily",
            ))

        if self.weekly_limit > 0:
            week_ago_iso = (now - timedelta(days=7)).isoformat()
            used = await tier3.get_token_usage_since(user_id=user_id, since_iso=week_ago_iso)
            ratio = used / self.weekly_limit
            if ratio >= 1.0:
                status = BudgetStatus.EXCEEDED
            elif ratio >= self.warn_threshold:
                status = BudgetStatus.WARN
            else:
                status = BudgetStatus.OK
            results.append(BudgetCheckResult(
                status=status, used=used, limit=self.weekly_limit,
                ratio=ratio, period="weekly",
            ))

        return results

    def should_block(self, results: list[BudgetCheckResult]) -> bool:
        """Return True if any budget is exceeded AND hard_stop is enabled."""
        if not self.hard_stop:
            return False
        return any(r.status == BudgetStatus.EXCEEDED for r in results)


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
