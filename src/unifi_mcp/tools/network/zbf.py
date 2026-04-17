"""Zone-Based Firewall (ZBF) tools: zones listing, policies CRUD.

Uses the Integration API for zones and V2 API for policies, per the endpoint catalog.
ZBF requires UniFi Network Application 9.0+.
"""

from unifi_mcp.auth.client import UnifiClient


def _format_zone(z: dict) -> dict:
    return {
        "id": z.get("id") or z.get("_id", ""),
        "name": z.get("name", ""),
        "description": z.get("description", ""),
        "networks": z.get("networkIds") or z.get("networks", []),
    }


async def list_zbf_zones(client: UnifiClient) -> list[dict]:
    """List all ZBF firewall zones."""
    response = await client.get(
        "/proxy/network/integration/v1/sites/{site_id}/firewall/zones",
        cache_category="zbf", cache_ttl=30.0,
    )
    if isinstance(response, list):
        zones = response
    else:
        zones = response.get("data", [])
    return [_format_zone(z) for z in zones]


async def get_zbf_zone(client: UnifiClient, zone_id: str) -> dict:
    """Get details for a specific ZBF zone."""
    response = await client.get(
        f"/proxy/network/integration/v1/sites/{{site_id}}/firewall/zones/{zone_id}",
        cache_category="zbf", cache_ttl=30.0,
    )
    if isinstance(response, dict) and "data" in response:
        data = response["data"]
        z = data[0] if isinstance(data, list) and data else data
    else:
        z = response
    return _format_zone(z if isinstance(z, dict) else {})


async def list_zbf_policies(client: UnifiClient) -> list[dict]:
    """List all ZBF firewall policies."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/firewall-policies",
        cache_category="zbf", cache_ttl=30.0,
    )
    if isinstance(response, list):
        policies = response
    else:
        policies = response.get("data", [])
    return [
        {
            "id": p.get("_id", ""),
            "name": p.get("name", ""),
            "source_zone_id": p.get("source_zone_id", ""),
            "destination_zone_id": p.get("destination_zone_id", ""),
            "action": p.get("action", ""),
            "protocol": p.get("protocol", "all"),
            "enabled": p.get("enabled", True),
            "index": p.get("index", 0),
        }
        for p in policies
    ]


async def create_zbf_policy(
    client: UnifiClient,
    name: str,
    source_zone_id: str,
    destination_zone_id: str,
    action: str = "ALLOW",
    protocol: str = "all",
    enabled: bool = True,
    confirm: bool = False,
) -> dict:
    """Create a new ZBF firewall policy. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "source_zone_id": source_zone_id,
        "destination_zone_id": destination_zone_id,
        "action": action,
        "protocol": protocol,
        "enabled": enabled,
    }

    if not confirm:
        return {
            "preview": True,
            "action": "create_zbf_policy",
            "params": payload,
            "message": f"Will create ZBF policy '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/v2/api/site/{site}/firewall-policies",
        json=payload,
    )
    client.invalidate_cache("zbf")
    return {"executed": True, "action": "create_zbf_policy", "response": response}


async def update_zbf_policy(
    client: UnifiClient,
    policy_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing ZBF policy. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "update_zbf_policy",
            "policy_id": policy_id,
            "updates": updates,
            "message": f"Will update ZBF policy {policy_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/v2/api/site/{{site}}/firewall-policies/{policy_id}",
        json=updates,
    )
    client.invalidate_cache("zbf")
    return {"executed": True, "action": "update_zbf_policy", "response": response}


async def delete_zbf_policy(client: UnifiClient, policy_id: str, confirm: bool = False) -> dict:
    """Delete a ZBF firewall policy. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_zbf_policy",
            "policy_id": policy_id,
            "message": f"Will delete ZBF policy {policy_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/v2/api/site/{{site}}/firewall-policies/{policy_id}",
    )
    client.invalidate_cache("zbf")
    return {"executed": True, "action": "delete_zbf_policy", "response": response}


TOOLS = [
    list_zbf_zones, get_zbf_zone, list_zbf_policies,
    create_zbf_policy, update_zbf_policy, delete_zbf_policy,
]
