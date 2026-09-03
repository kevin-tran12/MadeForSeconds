import time
from app.cache import MemoryCache


def test_memory_cache_set_get():
    cache = MemoryCache(ttl=10)
    cache.set("key", "value")
    assert cache.get("key") == "value"


def test_memory_cache_ttl_expiry():
    cache = MemoryCache(ttl=0.1)
    cache.set("key", "value")
    assert cache.get("key") == "value"
    time.sleep(0.2)
    assert cache.get("key") is None


def test_cache_clear():
    cache = MemoryCache(ttl=10)
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None


def test_memory_cache_delete():
    cache = MemoryCache(ttl=10)
    cache.set("key", "value")
    cache.delete("key")
    assert cache.get("key") is None


# ── Sous Chef counters: incr_by_with_ttl / get_counter ───────────────────────

def test_memory_incr_by_with_ttl_adds_and_refunds():
    cache = MemoryCache(ttl=10)
    assert cache.incr_by_with_ttl("k", 3, 60) == 3
    assert cache.incr_by_with_ttl("k", -1, 60) == 2
    assert cache.get_counter("k") == 2


def test_memory_get_counter_missing_or_expired_is_zero():
    cache = MemoryCache(ttl=10)
    assert cache.get_counter("nope") == 0
    cache.incr_by_with_ttl("k", 5, 0)  # expires immediately
    assert cache.get_counter("k") == 0


def test_memory_incr_with_ttl_still_starts_at_one():
    cache = MemoryCache(ttl=10)
    assert cache.incr_with_ttl("k", 60) == 1
    assert cache.incr_with_ttl("k", 60) == 2
    assert cache.get_counter("k") == 2


def test_memory_counters_survive_clear():
    cache = MemoryCache(ttl=10)
    cache.incr_by_with_ttl("k", 4, 60)
    cache.clear()
    assert cache.get_counter("k") == 4


def _redis_stub():
    from unittest.mock import MagicMock
    from app.cache import RedisCache
    cache = RedisCache.__new__(RedisCache)
    cache._NS = "mfs"
    cache._r = MagicMock()
    cache._incr_by_with_ttl_script = MagicMock(return_value=7)
    return cache


def test_redis_incr_by_with_ttl_runs_incrby_script_under_rl_prefix():
    cache = _redis_stub()
    assert cache.incr_by_with_ttl("llm:spend:2026-09", 5, 100) == 7
    cache._incr_by_with_ttl_script.assert_called_once_with(keys=["mfs:rl:llm:spend:2026-09"], args=[100, 5])


def test_redis_incr_by_with_ttl_error_is_none_not_minus_one():
    """A refunded counter can legitimately be negative, so the error sentinel
    must be None rather than incr_with_ttl's -1."""
    cache = _redis_stub()
    cache._incr_by_with_ttl_script.side_effect = ConnectionError("down")
    assert cache.incr_by_with_ttl("k", -1, 100) is None


def test_redis_get_counter_reads_raw_rl_key():
    cache = _redis_stub()
    cache._r.get.return_value = "42"
    assert cache.get_counter("llm:spend:2026-09") == 42
    cache._r.get.assert_called_once_with("mfs:rl:llm:spend:2026-09")
    cache._r.get.return_value = None
    assert cache.get_counter("absent") == 0
    cache._r.get.side_effect = ConnectionError("down")
    assert cache.get_counter("k") is None
