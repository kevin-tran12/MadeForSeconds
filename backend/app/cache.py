"""Simple in-memory TTL cache — no external dependencies required."""

import time
from typing import Any, Optional


class TTLCache:
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


# Module-level singletons shared across requests
recipes_cache = TTLCache(ttl=300)    # 5 minutes — recipes list + individual slugs
categories_cache = TTLCache(ttl=1800)  # 30 minutes — categories list rarely changes
