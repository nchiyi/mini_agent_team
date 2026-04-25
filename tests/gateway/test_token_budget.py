# tests/gateway/test_token_budget.py
"""
Unit tests for TokenBudget (src/gateway/rate_limit.py).

Test scenarios:
  1. Under threshold — OK status, no block
  2. At warn threshold (80%) — WARN status, no block even with hard_stop
  3. Exceeded (100%) hard_stop=False — EXCEEDED status but no block
  4. Exceeded (100%) hard_stop=True  — EXCEEDED status AND block
"""
import pytest
from unittest.mock import AsyncMock

from src.gateway.rate_limit import TokenBudget, BudgetStatus, BudgetCheckResult


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_tier3(daily_used: int = 0, weekly_used: int = 0) -> AsyncMock:
    """Return a mock Tier3Store that returns fixed token counts."""
    tier3 = AsyncMock()

    async def _usage_since(*, user_id: int, since_iso: str) -> int:
        # Distinguish daily (date-only ISO) from weekly (datetime ISO with T)
        if "T" in since_iso:
            return weekly_used
        return daily_used

    tier3.get_token_usage_since.side_effect = _usage_since
    return tier3


# ──────────────────────────────────────────────
# 1. Under threshold — all OK
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_under_threshold_ok():
    budget = TokenBudget(daily_limit=200_000, warn_threshold=0.8)
    tier3 = _make_tier3(daily_used=100_000)  # 50% usage
    results = await budget.check(user_id=1, tier3=tier3)
    assert len(results) == 1
    r = results[0]
    assert r.status == BudgetStatus.OK
    assert r.used == 100_000
    assert r.limit == 200_000
    assert r.period == "daily"
    assert r.remaining == 100_000
    assert not budget.should_block(results)


# ──────────────────────────────────────────────
# 2. At warn threshold (80%) — WARN, not blocked
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_at_warn_threshold():
    budget = TokenBudget(daily_limit=200_000, warn_threshold=0.8, hard_stop=True)
    tier3 = _make_tier3(daily_used=160_000)  # exactly 80%
    results = await budget.check(user_id=1, tier3=tier3)
    assert len(results) == 1
    r = results[0]
    assert r.status == BudgetStatus.WARN
    assert abs(r.ratio - 0.8) < 1e-9
    # Even with hard_stop=True, WARN should not block
    assert not budget.should_block(results)


# ──────────────────────────────────────────────
# 3. Exceeded — hard_stop=False → no block
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exceeded_soft_stop():
    budget = TokenBudget(daily_limit=200_000, warn_threshold=0.8, hard_stop=False)
    tier3 = _make_tier3(daily_used=210_000)  # 105%
    results = await budget.check(user_id=1, tier3=tier3)
    assert len(results) == 1
    r = results[0]
    assert r.status == BudgetStatus.EXCEEDED
    assert r.remaining == 0
    assert not budget.should_block(results)  # soft-stop: allow but warn


# ──────────────────────────────────────────────
# 4. Exceeded — hard_stop=True → block
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exceeded_hard_stop():
    budget = TokenBudget(daily_limit=200_000, warn_threshold=0.8, hard_stop=True)
    tier3 = _make_tier3(daily_used=200_001)  # just over limit
    results = await budget.check(user_id=1, tier3=tier3)
    assert len(results) == 1
    assert results[0].status == BudgetStatus.EXCEEDED
    assert budget.should_block(results)


# ──────────────────────────────────────────────
# 5. Both daily and weekly configured
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_and_weekly_both_checked():
    budget = TokenBudget(
        daily_limit=200_000,
        weekly_limit=1_000_000,
        warn_threshold=0.8,
    )
    tier3 = _make_tier3(daily_used=50_000, weekly_used=850_000)  # weekly at 85%
    results = await budget.check(user_id=1, tier3=tier3)
    assert len(results) == 2
    periods = {r.period: r for r in results}
    assert periods["daily"].status == BudgetStatus.OK
    assert periods["weekly"].status == BudgetStatus.WARN


# ──────────────────────────────────────────────
# 6. No budgets configured → empty results
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_budget_configured():
    budget = TokenBudget(daily_limit=0, weekly_limit=0)
    tier3 = _make_tier3(daily_used=999_999)
    results = await budget.check(user_id=1, tier3=tier3)
    assert results == []
    assert not budget.should_block(results)


# ──────────────────────────────────────────────
# 7. BudgetCheckResult convenience properties
# ──────────────────────────────────────────────

def test_budget_check_result_properties():
    r = BudgetCheckResult(
        status=BudgetStatus.WARN,
        used=160_000,
        limit=200_000,
        ratio=0.8,
        period="daily",
    )
    assert r.remaining == 40_000
    assert abs(r.pct - 80.0) < 1e-9
