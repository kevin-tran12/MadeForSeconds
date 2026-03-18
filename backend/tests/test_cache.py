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
