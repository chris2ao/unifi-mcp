"""Network/VLAN management tools: list, get, create, update, delete, DHCP leases."""

import re

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import check_id

TIER2_TOOLS: dict[str, str] = {
    "create_network": "networks",
    "update_network": "networks",
    "delete_network": "networks",
}

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_INTEGRATION_NETWORKS = "/proxy/network/integration/v1/sites/{site_id}/networks"
_MAX_IDS_PER_GROUP = 20


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


async def _to_integration_id(client: UnifiClient, network_id: str) -> str | None:
    """Map a legacy networkconf _id to an Integration network id via the network name.

    Integration ids are UUIDs and legacy _id values are 24-char hex strings, so
    they differ. UUIDs pass through unchanged. Returns None when no match exists.
    """
    if _UUID_RE.fullmatch(network_id):
        return network_id
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/rest/networkconf/{network_id}",
        cache_category="networks", cache_ttl=30.0,
    )
    rows = response.get("data", []) if isinstance(response, dict) else []
    name = rows[0].get("name") if rows and isinstance(rows[0], dict) else None
    if not name:
        return None
    for net in await client.get_all_pages(_INTEGRATION_NETWORKS):
        if isinstance(net, dict) and net.get("name") == name:
            return net.get("id")
    return None


def _group_references(network_id: str, response) -> dict:
    data = response.get("data", response) if isinstance(response, dict) else {}
    resources = data.get("referenceResources", []) if isinstance(data, dict) else []
    groups = []
    for res in resources:
        if not isinstance(res, dict):
            continue
        ids = [r.get("referenceId") for r in (res.get("references") or []) if isinstance(r, dict)]
        count = res.get("referenceCount")
        groups.append({
            "resource_type": res.get("resourceType", ""),
            "count": count if isinstance(count, int) else len(ids),
            "ids": ids[:_MAX_IDS_PER_GROUP],
        })
    total = sum(g["count"] for g in groups)
    return {
        "network_id": network_id,
        "referenced": total > 0,
        "total_references": total,
        "groups": groups,
    }


def _network_not_found(network_id: str) -> dict:
    return {
        "error": True,
        "category": "NOT_FOUND",
        "message": f"No network found with id '{network_id}'",
        "network_id": network_id,
    }


async def get_network_references(client: UnifiClient, network_id: str) -> dict:
    """List what still references a network (devices, clients, WiFi, routes, NAT).

    Use before deleting or changing a network. Accepts the Integration network
    id (UUID) or the legacy network id from list_networks. Output is grouped by
    resource type with counts and (up to 20) referencing ids.
    """
    err = check_id(network_id, "network_id")
    if err:
        return err
    try:
        integration_id = await _to_integration_id(client, network_id)
        if integration_id is None:
            return _network_not_found(network_id)
        response = await client.get(f"{_INTEGRATION_NETWORKS}/{integration_id}/references")
    except UnifiError as e:
        if e.category == ErrorCategory.NOT_FOUND:
            return _network_not_found(network_id)
        raise
    return _group_references(network_id, response)


async def _delete_preview_references(client: UnifiClient, network_id: str) -> dict:
    """Best-effort reference lookup for the delete preview; never raises."""
    try:
        result = await get_network_references(client, network_id)
    except Exception as e:  # noqa: BLE001 (lookup must never block the preview)
        return {"references_note": f"Reference lookup failed: {e}"}
    if result.get("error"):
        return {"references_note": f"Reference lookup unavailable: {result.get('message')}"}
    extra = {"references": result["groups"]}
    if result["referenced"]:
        extra["warning"] = (
            f"Network {network_id} is still referenced by {result['total_references']} "
            "resource(s). Deleting it may break them."
        )
    return extra


async def delete_network(client: UnifiClient, network_id: str, confirm: bool = False) -> dict:
    """Delete a network. Requires confirm=True after previewing.

    The preview lists resources that still reference the network.
    """
    if not confirm:
        return {
            "preview": True,
            "action": "delete_network",
            "network_id": network_id,
            "message": f"Will delete network {network_id}. This is irreversible. Call again with confirm=True to execute.",
            **await _delete_preview_references(client, network_id),
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
    delete_network, get_dhcp_leases, get_network_references,
]
