"""Redis-backed cache with in-memory fallback.

Primary invalidation is explicit (cache.clear() on admin mutations).
TTL is a 24-hour safety net only — content is never stale after an admin write.

Production: set REDIS_URL to a rediss:// Upstash endpoint (free tier, no VPC needed).
Local dev:  Docker Compose spins up a Redis container and sets REDIS_URL automatically.
No REDIS_URL: falls back silently to in-memory cache (no external dependency needed).
"""

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Serialisation helpers ──────────────────────────────────────────────────────

def _dumps(value: Any) -> str:
    """Serialise value to a JSON string, handling Pydantic models."""
    from pydantic import BaseModel
    if isinstance(value, list) and value and isinstance(value[0], BaseModel):
        return json.dumps([v.model_dump(mode="json") for v in value])
    if isinstance(value, BaseModel):
        return json.dumps(value.model_dump(mode="json"))
    return json.dumps(value)


def _loads(raw: str) -> Any:
    return json.loads(raw)


# ── Redis backend ──────────────────────────────────────────────────────────────

class RedisCache:
    """
    Shared, persistent cache backed by Redis.

    Keys are namespaced under `mfs:v{N}:` where N is a version counter stored
    in Redis itself.  cache.clear() simply increments N — all previous keys
    become unreachable in O(1) and expire naturally after TTL.  This avoids
    expensive KEYS / SCAN scans on every admin mutation.
    """

    _NS = "mfs"

    def __init__(self, url: str, ttl: int) -> None:
        import redis
        self._r = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._ttl = ttl

    def _version(self) -> str:
        return self._r.get(f"{self._NS}:version") or "1"

    def _key(self, key: str) -> str:
        return f"{self._NS}:v{self._version()}:{key}"

    def get(self, key: str) -> Optional[Any]:
        try:
            raw = self._r.get(self._key(key))
            return _loads(raw) if raw is not None else None
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        try:
            self._r.setex(self._key(key), self._ttl, _dumps(value))
        except Exception:
            pass

    def delete(self, key: str) -> None:
        try:
            self._r.delete(self._key(key))
        except Exception:
            pass

    def clear(self) -> None:
        """Invalidate all cached data in O(1) by bumping the version counter."""
        try:
            self._r.incr(f"{self._NS}:version")
        except Exception:
            pass

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment a rate-limit counter and set its expiry once.

        Bypasses _key()/_version() on purpose — rate-limit counters live outside
        the content-cache versioning scheme, so cache.clear() (an admin content
        mutation) must not reset them. Returns -1 on any backend error (sentinel
        for "treat as unavailable"), never raises.
        """
        try:
            raw_key = f"{self._NS}:rl:{key}"
            count = self._r.incr(raw_key)
            if count == 1:
                # Only the request that created the key (guaranteed unique via
                # INCR's atomicity) sets the TTL — no race, no NX flag needed.
                self._r.expire(raw_key, ttl_seconds)
            return count
        except Exception:
            return -1


# ── In-memory fallback ─────────────────────────────────────────────────────────

class MemoryCache:
    """Single-instance in-memory cache used when Redis is unavailable."""

    def __init__(self, ttl: int) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl
        # Separate from _store on purpose — rate-limit counters must not be
        # wiped by clear() (the content-cache invalidation hook).
        self._counters: dict[str, tuple[int, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() < expires_at:
            return value
        del self._store[key]
        return None

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (value, time.time() + self._ttl)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        now = time.time()
        entry = self._counters.get(key)
        if entry is None or now >= entry[1]:
            self._counters[key] = (1, now + ttl_seconds)
            return 1
        count = entry[0] + 1
        self._counters[key] = (count, entry[1])
        return count


# ── Singleton ──────────────────────────────────────────────────────────────────

# 24-hour TTL — since the cache is explicitly cleared on every admin mutation,
# this only fires when the site has been idle for a full day with no admin activity.
_TTL = 86_400


def _build() -> RedisCache | MemoryCache:
    from .config import settings

    if not settings.redis_url:
        # Expected locally and in CI; only noteworthy in production.
        logger.info("Cache: no REDIS_URL set, using in-memory cache")
        return MemoryCache(_TTL)

    try:
        c = RedisCache(settings.redis_url, _TTL)
        c._r.ping()
        logger.info("Cache: Redis connected")
        return c
    except Exception as exc:
        # WARNING, not info: REDIS_URL was configured, so someone intended a
        # shared cache and is not getting one. On Cloud Run this matters more
        # than it looks — the service scales to zero, so every cold start gets
        # an empty MemoryCache and the cache effectively never survives.
        # This previously logged via print() and went unnoticed for weeks.
        logger.warning(
            "Cache: REDIS_URL is set but Redis is unreachable (%s). "
            "Falling back to a per-instance in-memory cache.",
            exc,
        )
        return MemoryCache(_TTL)


cache = _build()
