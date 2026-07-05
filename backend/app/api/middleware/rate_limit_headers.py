"""Middleware that copies rate-limit info onto the response.

Endpoints protected by :func:`enforce_generate_rate_limit` stash the current
window's counters onto ``request.state.rate_limit_headers``. This middleware
copies them onto the response so clients can render "N left this hour".
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers: dict[str, str] | None = getattr(request.state, "rate_limit_headers", None)
        if headers:
            for k, v in headers.items():
                response.headers[k] = v
        return response
