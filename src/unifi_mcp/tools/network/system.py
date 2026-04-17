"""System information, health, alarms, and events tools."""

from unifi_mcp.auth.client import UnifiClient


def _format_uptime(seconds: int) -> str:
    """Convert seconds to human-readable uptime string."""
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"


async def get_system_info(client: UnifiClient) -> dict:
    """Get UniFi controller system information including version, hostname, and uptime."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/sysinfo",
        cache_category="system", cache_ttl=120.0,
    )
    info = response["data"][0]
    return {
        "hostname": info.get("hostname", ""),
        "name": info.get("name", ""),
        "version": info.get("version", ""),
        "build": info.get("build", ""),
        "timezone": info.get("timezone", ""),
        "uptime": info.get("uptime", 0),
        "uptime_human": _format_uptime(info.get("uptime", 0)),
        "update_available": info.get("update_available", False),
        "autobackup": info.get("autobackup", False),
    }


async def get_health(client: UnifiClient) -> list[dict]:
    """Get health status for all subsystems (WAN, WLAN, LAN, VPN)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/health",
        cache_category="system", cache_ttl=30.0,
    )
    return response["data"]


async def get_alarms(client: UnifiClient) -> list[dict]:
    """Get active alarms from the UniFi controller."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/alarm",
        cache_category="system", cache_ttl=30.0,
    )
    return response["data"]


_EVENT_CATEGORIES = {"triggers", "threats"}


async def get_events(
    client: UnifiClient, limit: int = 50, category: str = "triggers"
) -> list[dict]:
    """Get recent events from the UniFi controller's System Log.

    Network 9.x replaced the legacy `stat/event` endpoint with the System Log
    API. Two read-only categories are exposed via POST: `triggers` (general
    system events including device + admin activity) and `threats` (IDS/IPS).
    """
    if category not in _EVENT_CATEGORIES:
        return [{
            "error": True,
            "category": "VALIDATION_ERROR",
            "message": f"category must be one of {sorted(_EVENT_CATEGORIES)}",
        }]

    page_size = max(1, min(limit, 200))
    response = await client.post(
        f"/proxy/network/v2/api/site/{{site}}/system-log/{category}"
        f"?pageNumber=0&pageSize={page_size}",
        json={},
    )
    if isinstance(response, list):
        events = response
    else:
        events = response.get("data", [])
    return events[:limit]


TOOLS = [get_system_info, get_health, get_alarms, get_events]
