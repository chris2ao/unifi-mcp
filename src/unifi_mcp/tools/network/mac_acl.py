"""MAC ACL tools: list, add, delete filter rules.

Uses V2 API per the endpoint catalog:
/proxy/network/v2/api/site/{site}/acl-rules
"""

from unifi_mcp.auth.client import UnifiClient


async def list_mac_filter(client: UnifiClient) -> list[dict]:
    """List all MAC ACL filter rules."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/acl-rules",
        cache_category="mac_acl", cache_ttl=30.0,
    )
    if isinstance(response, list):
        rules = response
    else:
        rules = response.get("data", [])
    return [
        {
            "id": r.get("_id", ""),
            "name": r.get("name", ""),
            "action": r.get("action", ""),
            "mac_addresses": r.get("mac_addresses", []),
        }
        for r in rules
    ]


async def add_mac_filter(
    client: UnifiClient,
    name: str,
    action: str,
    mac_addresses: list[str],
    confirm: bool = False,
) -> dict:
    """Add a new MAC ACL filter rule. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "action": action,
        "mac_addresses": mac_addresses,
    }

    if not confirm:
        return {
            "preview": True,
            "action": "add_mac_filter",
            "params": payload,
            "message": f"Will add MAC ACL rule '{name}' ({action}). Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/v2/api/site/{site}/acl-rules",
        json=payload,
    )
    client.invalidate_cache("mac_acl")
    return {"executed": True, "action": "add_mac_filter", "name": name, "response": response}


async def delete_mac_filter(client: UnifiClient, rule_id: str, confirm: bool = False) -> dict:
    """Delete a MAC ACL filter rule. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_mac_filter",
            "rule_id": rule_id,
            "message": f"Will delete MAC ACL rule {rule_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/v2/api/site/{{site}}/acl-rules/{rule_id}",
    )
    client.invalidate_cache("mac_acl")
    return {"executed": True, "action": "delete_mac_filter", "rule_id": rule_id, "response": response}


TOOLS = [list_mac_filter, add_mac_filter, delete_mac_filter]
