"""Network/VLAN management tools: list, get, create, update, delete, DHCP leases."""

from unifi_mcp.auth.client import UnifiClient


def _format_network(n: dict) -> dict:
    return {
        "id": n.get("_id", ""),
        "name": n.get("name", ""),
        "purpose": n.get("purpose", ""),
        "subnet": n.get("ip_subnet", ""),
        "vlan_enabled": n.get("vlan_enabled", False),
        "vlan": n.get("vlan", None),
        "dhcpd_enabled": n.get("dhcpd_enabled", False),
        "dhcpd_start": n.get("dhcpd_start", ""),
        "dhcpd_stop": n.get("dhcpd_stop", ""),
        "domain_name": n.get("domain_name", ""),
        "networkgroup": n.get("networkgroup", ""),
    }


async def list_networks(client: UnifiClient) -> list[dict]:
    """List all configured networks/VLANs."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/networkconf",
        cache_category="networks", cache_ttl=30.0,
    )
    return [_format_network(n) for n in response["data"]]


async def get_network(client: UnifiClient, network_id: str) -> dict:
    """Get details for a specific network by ID."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/rest/networkconf/{network_id}",
        cache_category="networks", cache_ttl=30.0,
    )
    data = response.get("data", []) if isinstance(response, dict) else []
    if not data:
        return {
            "error": True,
            "category": "NOT_FOUND",
            "message": f"No network found with id '{network_id}'",
            "network_id": network_id,
        }
    return _format_network(data[0])


async def create_network(
    client: UnifiClient,
    name: str,
    purpose: str = "corporate",
    subnet: str = "",
    vlan: int | None = None,
    dhcpd_enabled: bool = True,
    dhcpd_start: str = "",
    dhcpd_stop: str = "",
    domain_name: str = "",
    confirm: bool = False,
) -> dict:
    """Create a new network/VLAN. Requires confirm=True after previewing."""
    payload = {"name": name, "purpose": purpose}
    if subnet:
        payload["ip_subnet"] = subnet
    if vlan is not None:
        payload["vlan_enabled"] = True
        payload["vlan"] = vlan
    if dhcpd_enabled:
        payload["dhcpd_enabled"] = True
        if dhcpd_start:
            payload["dhcpd_start"] = dhcpd_start
        if dhcpd_stop:
            payload["dhcpd_stop"] = dhcpd_stop
    if domain_name:
        payload["domain_name"] = domain_name

    if not confirm:
        return {
            "preview": True,
            "action": "create_network",
            "params": payload,
            "message": f"Will create network '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/networkconf",
        json=payload,
    )
    client.invalidate_cache("networks")
    return {"executed": True, "action": "create_network", "response": response}


async def update_network(
    client: UnifiClient,
    network_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "update_network",
            "network_id": network_id,
            "updates": updates,
            "message": f"Will update network {network_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/networkconf/{network_id}",
        json=updates,
    )
    client.invalidate_cache("networks")
    return {"executed": True, "action": "update_network", "response": response}


async def delete_network(client: UnifiClient, network_id: str, confirm: bool = False) -> dict:
    """Delete a network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_network",
            "network_id": network_id,
            "message": f"Will delete network {network_id}. This is irreversible. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/networkconf/{network_id}",
    )
    client.invalidate_cache("networks")
    return {"executed": True, "action": "delete_network", "response": response}


async def get_dhcp_leases(client: UnifiClient, network_id: str) -> list[dict]:
    """Get active DHCP leases for a specific network (filtered from active clients)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/sta",
        cache_category="clients", cache_ttl=15.0,
    )
    return [
        {
            "mac": c.get("mac", ""),
            "hostname": c.get("hostname", ""),
            "ip": c.get("ip", ""),
            "name": c.get("name", ""),
        }
        for c in response["data"]
        if c.get("network_id") == network_id
    ]


TOOLS = [
    list_networks, get_network, create_network, update_network,
    delete_network, get_dhcp_leases,
]
