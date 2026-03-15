"""Redis-backed cache with in-memory fallback.

Primary invalidation is explicit (cache.clear() on admin mutations).
TTL is a 24-hour safety net only — content is never stale after an admin write.

Production: set REDIS_URL to a rediss:// Upstash endpoint (free tier, no VPC needed).
Local dev:  Docker Compose spins up a Redis container and sets REDIS_URL automatically.
No REDIS_URL: falls back silently to in-memory cache (no external dependency needed).
"""

import json
import time
from typing import Any, Optional


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


# ── In-memory fallback ─────────────────────────────────────────────────────────

class MemoryCache:
    """Single-instance in-memory cache used when Redis is unavailable."""

    def __init__(self, ttl: int) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl

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


# ── Singleton ──────────────────────────────────────────────────────────────────

# 24-hour TTL — since the cache is explicitly cleared on every admin mutation,
# this only fires when the site has been idle for a full day with no admin activity.
_TTL = 86_400


def _build() -> RedisCache | MemoryCache:
    from .config import settings
    if settings.redis_url:
        try:
            c = RedisCache(settings.redis_url, _TTL)
            c._r.ping()
            print("[cache] Redis connected")
            return c
        except Exception as exc:
            print(f"[cache] Redis unavailable ({exc}), falling back to memory cache")
    else:
        print("[cache] No REDIS_URL set, using in-memory cache")
    return MemoryCache(_TTL)


cache = _build()
