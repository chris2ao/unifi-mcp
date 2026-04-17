"""Port profile management tools with PoE support: list, create, update, delete.

Uses V1 REST API per the endpoint catalog:
/proxy/network/api/s/{site}/rest/portconf
"""

from unifi_mcp.auth.client import UnifiClient


async def list_port_profiles(client: UnifiClient) -> list[dict]:
    """List all switch port profiles."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/portconf",
        cache_category="port_profiles", cache_ttl=30.0,
    )
    return [
        {
            "id": p.get("_id", ""),
            "name": p.get("name", ""),
            "native_networkconf_id": p.get("native_networkconf_id", ""),
            "poe_mode": p.get("poe_mode", ""),
            "forward": p.get("forward", ""),
        }
        for p in response["data"]
    ]


async def create_port_profile(
    client: UnifiClient,
    name: str,
    native_networkconf_id: str = "",
    poe_mode: str = "auto",
    forward: str = "all",
    confirm: bool = False,
) -> dict:
    """Create a new port profile. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "poe_mode": poe_mode,
        "forward": forward,
    }
    if native_networkconf_id:
        payload["native_networkconf_id"] = native_networkconf_id

    if not confirm:
        return {
            "preview": True,
            "action": "create_port_profile",
            "params": payload,
            "message": f"Will create port profile '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/portconf",
        json=payload,
    )
    client.invalidate_cache("port_profiles")
    return {"executed": True, "action": "create_port_profile", "response": response}


async def update_port_profile(
    client: UnifiClient,
    profile_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing port profile. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "update_port_profile",
            "profile_id": profile_id,
            "updates": updates,
            "message": f"Will update port profile {profile_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/portconf/{profile_id}",
        json=updates,
    )
    client.invalidate_cache("port_profiles")
    return {"executed": True, "action": "update_port_profile", "response": response}


async def delete_port_profile(client: UnifiClient, profile_id: str, confirm: bool = False) -> dict:
    """Delete a port profile. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_port_profile",
            "profile_id": profile_id,
            "message": f"Will delete port profile {profile_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/portconf/{profile_id}",
    )
    client.invalidate_cache("port_profiles")
    return {"executed": True, "action": "delete_port_profile", "response": response}


TOOLS = [list_port_profiles, create_port_profile, update_port_profile, delete_port_profile]
