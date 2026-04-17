"""Client management tools: list, get, block, unblock, reconnect, alias, history, list_all."""

from unifi_mcp.auth.client import UnifiClient


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


async def get_client_history(client: UnifiClient, mac: str) -> list[dict]:
    """Get hourly usage history for a client."""
    response = await client.post(
        "/proxy/network/api/s/{site}/stat/report/hourly.user",
        json={"attrs": ["rx_bytes", "tx_bytes"], "mac": mac},
    )
    return response["data"]


TOOLS = [
    list_clients, get_client, block_client, unblock_client,
    reconnect_client, set_client_alias, list_all_clients, get_client_history,
]
