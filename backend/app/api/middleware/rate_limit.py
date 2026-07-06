"""Fixed-window rate limiter backed by Redis.

Keyed per client identity + hour bucket. Falls back to open-allow if Redis is
unavailable (v0.1 tolerates lax limiting rather than dropping legitimate
traffic during infra hiccups).

Identity resolution:
    - Authenticated (JWT present + valid) → user_id
    - Otherwise → client IP (first X-Forwarded-For hop, else request.client.host)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.logging_config import get_logger
from app.repository.user_repo import UserRepository
from app.services.auth_service import AuthError, AuthService

logger = get_logger(__name__)

_HOUR_SECONDS = 3600


@dataclass
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class RateLimiter:
    """Thin wrapper around a Redis async client.

    Keys: ``ratelimit:{scope}:{identity}:{hour_bucket}``
        scope    → "anon" | "user"
        identity → ip or user_id
        hour     → epoch // 3600
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        settings = get_settings()
        self._anon_limit = settings.rate_limit_anon_per_hour
        self._user_limit = settings.rate_limit_user_per_hour

    async def check(self, *, scope: str, identity: str) -> RateLimitDecision:
        limit = self._user_limit if scope == "user" else self._anon_limit
        now = int(time.time())
        bucket = now // _HOUR_SECONDS
        key = f"ratelimit:{scope}:{identity}:{bucket}"

        try:
            # INCR then set TTL only on the first hit (idempotent otherwise).
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, _HOUR_SECONDS)
            ttl = await self._redis.ttl(key)
        except RedisError as e:
            logger.warning("ratelimit_redis_error_open", error=str(e), key=key)
            # Fail open — v0.1 policy.
            return RateLimitDecision(True, limit, limit, _HOUR_SECONDS)

        remaining = max(0, limit - int(count))
        reset = ttl if isinstance(ttl, int) and ttl >= 0 else _HOUR_SECONDS
        return RateLimitDecision(
            allowed=int(count) <= limit,
            limit=limit,
            remaining=remaining,
            reset_seconds=reset,
        )


# ---------- FastAPI dependency ----------


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_generate_rate_limit(request: Request) -> None:
    """Dependency to attach to `/generate` endpoints.

    Resolves identity (user_id or IP) and rejects with 429 when the hour bucket
    is exhausted. Adds `X-RateLimit-*` headers to the response via mutation of
    ``request.state.rate_limit_headers`` — the response middleware picks them up.
    """
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is None:
        # Redis not wired up (e.g. tests) → don't rate-limit.
        return

    # Try to resolve auth without raising; falls back to anon IP.
    scope, identity = await _resolve_identity(request)

    decision = await limiter.check(scope=scope, identity=identity)
    request.state.rate_limit_headers = {
        "X-RateLimit-Limit": str(decision.limit),
        "X-RateLimit-Remaining": str(decision.remaining),
        "X-RateLimit-Reset": str(decision.reset_seconds),
    }
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limited",
                "limit": decision.limit,
                "reset_seconds": decision.reset_seconds,
                "scope": scope,
            },
            headers={
                "Retry-After": str(decision.reset_seconds),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(decision.reset_seconds),
            },
        )


async def _resolve_identity(request: Request) -> tuple[str, str]:
    """Return ``(scope, identity)`` for the current request."""
    authz = request.headers.get("authorization")
    if authz and authz.lower().startswith("bearer "):
        token = authz.split(" ", 1)[1].strip()
        try:
            async with AsyncSessionLocal() as session:
                auth = AuthService(UserRepository(session))
                user_id = auth.decode_token(token)
                return "user", str(user_id)
        except AuthError:
            # Bad/expired token → treat as anon (IP).
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("ratelimit_identity_decode_failed", error=str(e))

    return "anon", _client_ip(request)
