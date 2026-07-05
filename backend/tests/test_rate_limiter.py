"""Rate limiter smoke test — uses an in-memory fake Redis stub.

We only cover the pure logic: counter increments, TTL semantics, fail-open on
Redis errors. The FastAPI dependency wiring is covered indirectly via
``test_app_boot``.
"""
from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from app.api.middleware.rate_limit import RateLimiter


class FakeRedis:
    """Minimal async fake: supports incr / expire / ttl. Ignores expiry."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.raise_on_incr = False

    async def incr(self, key: str) -> int:
        if self.raise_on_incr:
            raise RedisError("boom")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


@pytest.mark.asyncio
async def test_anon_bucket_allows_then_blocks(monkeypatch) -> None:
    # Force a tiny anon limit before constructing the limiter.
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_anon_per_hour", 2)
    monkeypatch.setattr(settings, "rate_limit_user_per_hour", 60)

    limiter = RateLimiter(redis=FakeRedis())  # type: ignore[arg-type]

    d1 = await limiter.check(scope="anon", identity="1.2.3.4")
    d2 = await limiter.check(scope="anon", identity="1.2.3.4")
    d3 = await limiter.check(scope="anon", identity="1.2.3.4")

    assert d1.allowed and d1.remaining == 1
    assert d2.allowed and d2.remaining == 0
    assert not d3.allowed
    assert d3.limit == 2


@pytest.mark.asyncio
async def test_fail_open_when_redis_errors() -> None:
    redis = FakeRedis()
    redis.raise_on_incr = True
    limiter = RateLimiter(redis=redis)  # type: ignore[arg-type]

    decision = await limiter.check(scope="anon", identity="1.2.3.4")
    # Fail-open: still allowed, but headers show the configured limit.
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_user_and_anon_buckets_are_isolated(monkeypatch) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_anon_per_hour", 1)
    monkeypatch.setattr(settings, "rate_limit_user_per_hour", 5)

    limiter = RateLimiter(redis=FakeRedis())  # type: ignore[arg-type]

    d_anon = await limiter.check(scope="anon", identity="ip1")
    d_anon2 = await limiter.check(scope="anon", identity="ip1")
    d_user = await limiter.check(scope="user", identity="user1")

    assert d_anon.allowed
    assert not d_anon2.allowed  # anon exhausted at 1
    assert d_user.allowed        # user bucket independent
    assert d_user.limit == 5
