"""Client management tools: list, get, block, unblock, reconnect, alias, history, list_all."""

import time

from unifi_mcp.auth.client import UnifiClient

# Default look-back for client history when no explicit range is given (30 days).
_HISTORY_DEFAULT_LOOKBACK_MS = 30 * 24 * 60 * 60 * 1000


def _format_bytes(b: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _format_uptime(seconds: int) -> str:
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


def _format_client(c: dict) -> dict:
    return {
        "id": c.get("_id", ""),
        "mac": c.get("mac", ""),
        "hostname": c.get("hostname", ""),
        "ip": c.get("ip", ""),
        "name": c.get("name", ""),
        "network": c.get("network", ""),
        "is_wired": c.get("is_wired", False),
        "is_guest": c.get("is_guest", False),
        "uptime": c.get("uptime", 0),
        "uptime_human": _format_uptime(c.get("uptime", 0)),
        "tx_bytes": c.get("tx_bytes", 0),
        "tx_human": _format_bytes(c.get("tx_bytes", 0)),
        "rx_bytes": c.get("rx_bytes", 0),
        "rx_human": _format_bytes(c.get("rx_bytes", 0)),
        # Wired clients carry their volume under wired-* counters; /stat/sta puts
        # 0 in tx_bytes/rx_bytes for them. Surface both so callers can pick.
        "wired_tx_bytes": c.get("wired-tx_bytes", 0),
        "wired_rx_bytes": c.get("wired-rx_bytes", 0),
        "signal": c.get("signal", 0),
        "satisfaction": c.get("satisfaction", 0),
        "blocked": c.get("blocked", False),
    }


async def list_clients(client: UnifiClient) -> list[dict]:
    """List all currently connected (active) clients."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/sta",
        cache_category="clients", cache_ttl=15.0,
    )
    return [_format_client(c) for c in response["data"]]


async def get_client(client: UnifiClient, mac: str) -> dict:
    """Get details for a specific client by MAC address."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/sta/{mac}",
        cache_category="clients", cache_ttl=15.0,
    )
    return _format_client(response["data"][0])


async def block_client(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Block a client from the network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "block_client",
            "mac": mac,
            "message": f"Will block client {mac} from the network. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/stamgr",
        json={"cmd": "block-sta", "mac": mac},
    )
    client.invalidate_cache("clients")
    return {"executed": True, "action": "block_client", "mac": mac, "response": response}


async def unblock_client(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Unblock a previously blocked client. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "unblock_client",
            "mac": mac,
            "message": f"Will unblock client {mac}. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/stamgr",
        json={"cmd": "unblock-sta", "mac": mac},
    )
    client.invalidate_cache("clients")
    return {"executed": True, "action": "unblock_client", "mac": mac, "response": response}


async def reconnect_client(client: UnifiClient, mac: str) -> dict:
    """Force a client to reconnect (kick and rejoin). Tier 1, non-destructive."""
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/stamgr",
        json={"cmd": "kick-sta", "mac": mac},
    )
    return {"action": "reconnect_client", "mac": mac, "response": response}


async def set_client_alias(client: UnifiClient, client_id: str, name: str) -> dict:
    """Set a friendly name (alias) for a client. Tier 1, cosmetic change."""
    return await client.put(
        f"/proxy/network/api/s/{{site}}/rest/user/{client_id}",
        json={"name": name},
    )


async def list_all_clients(client: UnifiClient) -> list[dict]:
    """List all known clients (historical, including offline)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/user",
        cache_category="clients", cache_ttl=30.0,
    )
    return [
        {
            "id": c.get("_id", ""),
            "mac": c.get("mac", ""),
            "hostname": c.get("hostname", ""),
            "name": c.get("name", ""),
        }
        for c in response["data"]
    ]


_HISTORY_INTERVALS = ("hourly", "daily")


async def get_client_history(
    client: UnifiClient,
    mac: str,
    start: int | None = None,
    end: int | None = None,
    interval: str = "hourly",
) -> list[dict]:
    """Get per-client usage history at the given report interval.

    Returns one entry per bucket with ``time`` (epoch milliseconds), ``rx_bytes``
    and ``tx_bytes``. ``start``/``end`` are epoch milliseconds; when omitted the
    range defaults to the last 30 days ending now. The ``time`` attr is requested
    explicitly so each bucket is timestamped (the controller omits it otherwise).

    ``interval`` selects the controller report: ``hourly`` (retained ~7 days) or
    ``daily`` (retained ~30+ days, used for the 30-day window). Unknown values
    fall back to ``hourly``.
    """
    if interval not in _HISTORY_INTERVALS:
        interval = "hourly"
    if end is None:
        end = int(time.time() * 1000)
    if start is None:
        start = end - _HISTORY_DEFAULT_LOOKBACK_MS
    response = await client.post(
        f"/proxy/network/api/s/{{site}}/stat/report/{interval}.user",
        json={
            "attrs": ["time", "rx_bytes", "tx_bytes"],
            "start": start,
            "end": end,
            "mac": mac,
        },
    )
    return response["data"]


TOOLS = [
    list_clients, get_client, block_client, unblock_client,
    reconnect_client, set_client_alias, list_all_clients, get_client_history,
]
