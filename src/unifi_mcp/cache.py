import time
from typing import Any


class TTLCache:
    """In-memory cache with per-entry TTL and category-based invalidation."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        """Return cached value if present and not expired, else None."""
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        """Store a value with a TTL in seconds."""
        self._store[key] = (time.monotonic() + ttl, value)

    def invalidate(self, category: str) -> None:
        """Remove all entries whose key starts with the given category prefix."""
        prefix = f"{category}:"
        keys_to_remove = [k for k in self._store if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._store[key]

    def clear(self) -> None:
        """Remove all entries."""
        self._store.clear()
