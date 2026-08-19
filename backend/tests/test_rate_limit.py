import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.cache import MemoryCache, RedisCache
from app.rate_limit import rate_limit


# ── cache.incr_with_ttl ──────────────────────────────────────────────────────

def test_incr_with_ttl_memory_increments_and_expires():
    cache = MemoryCache(ttl=86_400)
    assert cache.incr_with_ttl("k", 1) == 1
    assert cache.incr_with_ttl("k", 1) == 2
    assert cache.incr_with_ttl("k", 1) == 3
    time.sleep(1.1)
    assert cache.incr_with_ttl("k", 1) == 1


def test_incr_with_ttl_memory_isolated_keys():
    cache = MemoryCache(ttl=86_400)
    assert cache.incr_with_ttl("a", 60) == 1
    assert cache.incr_with_ttl("b", 60) == 1
    assert cache.incr_with_ttl("a", 60) == 2
    assert cache.incr_with_ttl("b", 60) == 2


def test_incr_with_ttl_memory_does_not_clear_on_cache_clear():
    cache = MemoryCache(ttl=86_400)
    cache.incr_with_ttl("k", 60)
    cache.incr_with_ttl("k", 60)
    cache.set("some-content-key", "value")
    cache.clear()  # content-cache invalidation — must not touch rate-limit counters
    assert cache.incr_with_ttl("k", 60) == 3


def test_incr_with_ttl_redis_increments_and_sets_expire_once():
    cache = RedisCache.__new__(RedisCache)
    cache._NS = "mfs"
    cache._r = MagicMock()
    cache._r.incr.return_value = 1
    assert cache.incr_with_ttl("checkout:1.2.3.4", 60) == 1
    cache._r.incr.assert_called_once_with("mfs:rl:checkout:1.2.3.4")
    cache._r.expire.assert_called_once_with("mfs:rl:checkout:1.2.3.4", 60)

    cache._r.incr.return_value = 2
    assert cache.incr_with_ttl("checkout:1.2.3.4", 60) == 2
    # expire is only set on the first increment, not subsequent ones
    cache._r.expire.assert_called_once()


def test_incr_with_ttl_redis_returns_negative_one_on_error():
    cache = RedisCache.__new__(RedisCache)
    cache._NS = "mfs"
    cache._r = MagicMock()
    cache._r.incr.side_effect = Exception("connection refused")
    assert cache.incr_with_ttl("k", 60) == -1


# ── rate_limit dependency ────────────────────────────────────────────────────

@pytest.fixture
def rl_app():
    app = FastAPI()

    @app.get("/limited", dependencies=[Depends(rate_limit("t", 2, 60))])
    async def limited():
        return {"ok": True}

    return app


def test_rate_limit_dependency_allows_under_limit(rl_app):
    with TestClient(rl_app) as client:
        assert client.get("/limited").status_code == 200
        assert client.get("/limited").status_code == 200


def test_rate_limit_dependency_blocks_over_limit_with_retry_after(rl_app):
    with TestClient(rl_app) as client:
        client.get("/limited")
        client.get("/limited")
        response = client.get("/limited")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"


def test_rate_limit_dependency_fails_open_on_backend_error(rl_app):
    with patch("app.rate_limit.cache") as mock_cache:
        mock_cache.incr_with_ttl.return_value = -1
        with TestClient(rl_app) as client:
            for _ in range(5):
                assert client.get("/limited").status_code == 200
