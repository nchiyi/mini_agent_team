import asyncio
import pytest
from src.gateway.rate_limit import RateLimiter


def test_allows_up_to_burst():
    rl = RateLimiter(per_user_per_minute=60, burst=3, enabled=True)
    assert rl.check(1) is True
    assert rl.check(1) is True
    assert rl.check(1) is True
    assert rl.check(1) is False  # burst exhausted


def test_different_users_independent():
    rl = RateLimiter(per_user_per_minute=60, burst=1, enabled=True)
    assert rl.check(1) is True
    assert rl.check(1) is False
    assert rl.check(2) is True  # separate bucket


def test_disabled_always_allows():
    rl = RateLimiter(per_user_per_minute=1, burst=1, enabled=False)
    for _ in range(20):
        assert rl.check(99) is True


def test_burst_20_only_burst_pass():
    """Integration: burst=3 → only first 3 of 20 rapid requests allowed."""
    rl = RateLimiter(per_user_per_minute=60, burst=3, enabled=True)
    results = [rl.check(7) for _ in range(20)]
    assert results[:3] == [True, True, True]
    assert all(r is False for r in results[3:])


def test_tokens_refill_over_time():
    import time
    rl = RateLimiter(per_user_per_minute=600, burst=1, enabled=True)  # 10 tok/s
    assert rl.check(1) is True
    assert rl.check(1) is False  # bucket empty

    # Manually advance the bucket's last_refill timestamp by 0.15s → ≥1 token refilled
    bucket = rl._buckets[1]
    bucket.last_refill -= 0.15
    assert rl.check(1) is True


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    rl = RateLimiter(per_user_per_minute=600, burst=100, max_concurrent=2, enabled=True)
    in_flight = []
    max_observed = [0]

    async def task():
        async with rl.semaphore:
            in_flight.append(1)
            max_observed[0] = max(max_observed[0], len(in_flight))
            await asyncio.sleep(0.01)
            in_flight.pop()

    await asyncio.gather(*[task() for _ in range(10)])
    assert max_observed[0] <= 2
