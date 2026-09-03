import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.cache import MemoryCache, RedisCache, _MAX_COUNTERS
from app.rate_limit import _client_ip, rate_limit


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


def test_incr_with_ttl_redis_calls_registered_script_atomically():
    """INCR+EXPIRE run as one Lua script (single round-trip), not two separate
    calls — a dropped connection between two separate calls could otherwise
    leave a key with no TTL, stuck over its limit forever."""
    cache = RedisCache.__new__(RedisCache)
    cache._NS = "mfs"
    cache._incr_with_ttl_script = MagicMock(return_value=1)
    assert cache.incr_with_ttl("checkout:1.2.3.4", 60) == 1
    cache._incr_with_ttl_script.assert_called_once_with(keys=["mfs:rl:checkout:1.2.3.4"], args=[60])


def test_incr_with_ttl_redis_returns_negative_one_on_error():
    cache = RedisCache.__new__(RedisCache)
    cache._NS = "mfs"
    cache._incr_with_ttl_script = MagicMock(side_effect=Exception("connection refused"))
    assert cache.incr_with_ttl("k", 60) == -1


def test_redis_cache_init_registers_incr_with_ttl_script():
    with patch("redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_from_url.return_value = mock_client
        RedisCache("redis://localhost:6379", ttl=100)
        # Both counter scripts: INCR (rate limits) and INCRBY (Sous Chef spend/quota).
        assert mock_client.register_script.call_count == 2
        script_text = mock_client.register_script.call_args_list[0][0][0]
        assert "INCR" in script_text and "EXPIRE" in script_text


# ── MemoryCache counter bound (mirrors the old limiter's key cap) ───────────

def test_memory_cache_evicts_when_over_max_counters():
    cache = MemoryCache(ttl=86_400)
    for i in range(_MAX_COUNTERS + 1):
        cache.incr_with_ttl(f"k{i}", 86_400)
    assert len(cache._counters) == _MAX_COUNTERS + 1

    # Next insert is over the cap; nothing has expired, so it clears entirely
    # rather than growing further, instead of leaking memory forever.
    cache.incr_with_ttl("trigger", 86_400)
    assert len(cache._counters) == 1


# ── _client_ip (Cloud Run: request.client.host is the GFE hop, not the visitor) ──

def _make_request(headers=None, client_host="10.0.0.1"):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or [])]
    scope = {"type": "http", "headers": raw_headers, "client": (client_host, 1234)}
    return Request(scope)


def test_client_ip_prefers_rightmost_entry_ignoring_spoofed_prefix():
    """Google's documented format is <client-supplied, unverified>, ...,
    <value GFE appended> — the real client IP is whatever the trusted hop
    appended (rightmost), not whatever the client claimed (leftmost, fully
    spoofable). An attacker sending a fresh fake leftmost value on every
    request must not be able to dodge the limit."""
    request = _make_request(headers=[("X-Forwarded-For", "9.9.9.9, 1.1.1.1")], client_host="10.0.0.1")
    assert _client_ip(request) == "1.1.1.1"


def test_client_ip_single_entry_no_spoofing_attempted():
    request = _make_request(headers=[("X-Forwarded-For", "1.1.1.1")], client_host="10.0.0.1")
    assert _client_ip(request) == "1.1.1.1"


def test_client_ip_malformed_rightmost_entry_falls_back_to_socket_peer():
    request = _make_request(headers=[("X-Forwarded-For", "not-an-ip")], client_host="10.0.0.1")
    assert _client_ip(request) == "10.0.0.1"


def test_client_ip_falls_back_to_socket_peer_without_header():
    request = _make_request(headers=[], client_host="10.0.0.1")
    assert _client_ip(request) == "10.0.0.1"


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


def test_rate_limit_dependency_falls_back_to_local_counter_on_backend_error(rl_app):
    """A Redis error must not disable rate limiting entirely — that would
    also strip brute-force protection from TOTP verify/reset during an
    outage. It degrades to a local counter instead, which still enforces
    the limit (this deployment runs a single Cloud Run instance, so a local
    counter is just as authoritative as Redis would have been here)."""
    from app.rate_limit import _fallback
    _fallback._counters.clear()
    with patch("app.rate_limit.cache") as mock_cache:
        mock_cache.incr_with_ttl.return_value = -1
        with TestClient(rl_app) as client:
            assert client.get("/limited").status_code == 200
            assert client.get("/limited").status_code == 200
            assert client.get("/limited").status_code == 429


def test_rate_limit_dependency_buckets_by_x_forwarded_for(rl_app):
    """Regression test: on Cloud Run, request.client.host is the GFE hop, not
    the visitor — two different visitors must not share one bucket, and one
    visitor's traffic must not block everyone else's."""
    with TestClient(rl_app) as client:
        for _ in range(2):
            assert client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 200
        assert client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1"}).status_code == 429

        # A different forwarded client is an independent bucket, not blocked
        # by the first client's traffic.
        assert client.get("/limited", headers={"X-Forwarded-For": "2.2.2.2"}).status_code == 200
