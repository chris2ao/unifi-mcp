from datetime import datetime, timezone


class DiscoveryRegistry:
    """Tracks API request results for auth discovery documentation."""

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def log(self, endpoint: str, method: str, status_code: int) -> None:
        """Record a request result."""
        self._entries.append({
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_report(self) -> list[dict]:
        """Return all logged entries."""
        return list(self._entries)

    def get_auth_failures(self) -> list[dict]:
        """Return only entries where API key auth failed (401/403)."""
        return [e for e in self._entries if e["status_code"] in (401, 403)]

    def get_summary(self) -> dict:
        """Return aggregate counts."""
        total = len(self._entries)
        successful = sum(1 for e in self._entries if 200 <= e["status_code"] < 400)
        auth_failures = sum(1 for e in self._entries if e["status_code"] in (401, 403))
        return {
            "total_requests": total,
            "successful": successful,
            "auth_failures": auth_failures,
            "success_rate": round((successful / total) * 100, 1) if total > 0 else 0.0,
        }

    def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()
