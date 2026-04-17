import time
from unifi_mcp.cache import TTLCache


def test_cache_set_and_get():
    cache = TTLCache()
    cache.set("devices:/api/stat/device", [{"name": "AP-1"}], ttl=30.0)
    result = cache.get("devices:/api/stat/device")
    assert result == [{"name": "AP-1"}]


def test_cache_miss_returns_none():
    cache = TTLCache()
    assert cache.get("nonexistent") is None


def test_cache_expiry():
    cache = TTLCache()
    cache.set("key", "value", ttl=0.01)  # 10ms TTL
    time.sleep(0.02)
    assert cache.get("key") is None


def test_cache_invalidate_by_category():
    cache = TTLCache()
    cache.set("devices:/api/stat/device", "list", ttl=30.0)
    cache.set("devices:/api/stat/device/abc", "detail", ttl=30.0)
    cache.set("clients:/api/stat/sta", "clients", ttl=30.0)
    cache.invalidate("devices")
    assert cache.get("devices:/api/stat/device") is None
    assert cache.get("devices:/api/stat/device/abc") is None
    assert cache.get("clients:/api/stat/sta") == "clients"


def test_cache_clear():
    cache = TTLCache()
    cache.set("a", 1, ttl=30.0)
    cache.set("b", 2, ttl=30.0)
    cache.clear()
    assert cache.get("a") is None
    assert cache.get("b") is None


def test_cache_overwrite():
    cache = TTLCache()
    cache.set("key", "old", ttl=30.0)
    cache.set("key", "new", ttl=30.0)
    assert cache.get("key") == "new"
