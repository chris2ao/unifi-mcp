"""VPN tools: list servers and clients.

Uses V1 REST API, filtering networkconf by purpose, per the endpoint catalog.
"""

from unifi_mcp.auth.client import UnifiClient


async def list_vpn_servers(client: UnifiClient) -> list[dict]:
    """List all VPN server configurations."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/networkconf",
        cache_category="vpn", cache_ttl=30.0,
    )
    return [
        {
            "id": n.get("_id", ""),
            "name": n.get("name", ""),
            "purpose": n.get("purpose", ""),
            "enabled": n.get("enabled", False),
        }
        for n in response["data"]
        if "vpn-server" in n.get("purpose", "") or n.get("purpose", "") == "vpn-server"
    ]


async def list_vpn_clients(client: UnifiClient) -> list[dict]:
    """List all VPN client configurations."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/networkconf",
        cache_category="vpn", cache_ttl=30.0,
    )
    return [
        {
            "id": n.get("_id", ""),
            "name": n.get("name", ""),
            "purpose": n.get("purpose", ""),
            "enabled": n.get("enabled", False),
        }
        for n in response["data"]
        if "vpn-client" in n.get("purpose", "") or n.get("purpose", "") == "vpn-client"
    ]


TOOLS = [list_vpn_servers, list_vpn_clients]
