"""Shared IP-based rate limiting for sensitive endpoints.

Backed by cache.incr_with_ttl (atomic INCR+conditional-EXPIRE) on whichever
cache backend is active (Redis, or in-memory on a single Cloud Run instance).
Fails open on backend errors, consistent with every other cache.py call site.
"""

import logging

from fastapi import HTTPException, Request

from .cache import cache

logger = logging.getLogger(__name__)


def rate_limit(name: str, limit: int, window_seconds: int):
    """FastAPI dependency factory: `limit` requests per `window_seconds` per client IP.

    Usage: @router.post(..., dependencies=[Depends(rate_limit("checkout", 20, 3600))])
    """

    async def _dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        count = cache.incr_with_ttl(f"{name}:{ip}", window_seconds)
        if count <= 0:
            # incr_with_ttl returns -1 when the backend errored — fail open.
            logger.warning("rate_limit(%s): backend unavailable, failing open", name)
            return
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(window_seconds)},
            )

    return _dependency
