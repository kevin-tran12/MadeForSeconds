"""Shared IP-based rate limiting for sensitive endpoints.

Backed by cache.incr_with_ttl (atomic INCR+conditional-EXPIRE) on whichever
cache backend is active (Redis, or in-memory on a single Cloud Run instance),
falling back to a local counter if the primary backend errors.
"""

import ipaddress
import logging

from fastapi import HTTPException, Request

from .cache import MemoryCache, cache

logger = logging.getLogger(__name__)

# Used only when the primary cache backend (Redis) errors on a given call —
# see rate_limit() below. A local, single-instance counter is strictly
# better than disabling rate limiting entirely while Redis is unavailable,
# and this deployment runs a single Cloud Run instance, so it's just as
# authoritative as Redis would have been here.
_fallback = MemoryCache(ttl=3600)


def _client_ip(request: Request) -> str:
    """Best-effort real client IP.

    On Cloud Run, request.client.host is the ASGI-level socket peer — the
    Google Front End hop, not the visitor — so keying on it alone would
    collapse every user into one shared rate-limit bucket.

    X-Forwarded-For, when present, is trustworthy here because Cloud Run's
    ingress can't be bypassed — there is no path to the container that skips
    the GFE hop that sets it. But the TRUSTWORTHY part is whatever GFE itself
    appended, not whatever the client sent: Google's documented format is
    "<client-supplied, unverified>, ..., <value the proxy appended>", so the
    real client IP is the RIGHTMOST entry (this project's Cloud Run service
    uses default ingress with no separate external load balancer in front,
    so GFE appends exactly one hop). Trusting the leftmost entry instead
    would let an attacker send a fresh fake value on every request and
    bypass every limit entirely.
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            candidate = parts[-1]
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass
    return request.client.host if request.client else "unknown"


def count_hit(key: str, window_seconds: int) -> int:
    """Atomically increment `key`'s hit count within `window_seconds` and
    return the new count.

    Shared primitive behind every rate limit in this app, HTTP (`rate_limit`
    below) and MCP (`mcp_server/rate_budgets.py`) alike — one place owns the
    "primary cache, fall back to a local counter on backend error" behavior
    rather than each caller reimplementing it.
    """
    count = cache.incr_with_ttl(key, window_seconds)
    if count <= 0:
        # incr_with_ttl returns -1 when the backend errored. Falling back to
        # a local counter keeps abuse protection in place during a Redis
        # outage instead of disabling it entirely.
        logger.warning("count_hit(%s): backend unavailable, using local fallback counter", key)
        count = _fallback.incr_with_ttl(key, window_seconds)
    return count


def rate_limit(name: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: `limit` requests per `window_seconds` per client IP.

    Usage: @router.post(..., dependencies=[Depends(rate_limit("checkout", 20, 3600))])
    """

    async def _dependency(request: Request) -> None:
        ip = _client_ip(request)
        key = f"{name}:{ip}"
        count = count_hit(key, window_seconds)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
