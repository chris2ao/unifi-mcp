"""RADIUS profile management tools: list, create, update, delete.

Uses V1 REST API per the endpoint catalog:
/proxy/network/api/s/{site}/rest/radiusprofile
"""

from unifi_mcp.auth.client import UnifiClient


async def list_radius_profiles(client: UnifiClient) -> list[dict]:
    """List all RADIUS server profiles."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/radiusprofile",
        cache_category="radius", cache_ttl=30.0,
    )
    return [
        {
            "id": p.get("_id", ""),
            "name": p.get("name", ""),
            "auth_servers": p.get("auth_servers", []),
            "acct_servers": p.get("acct_servers", []),
        }
        for p in response["data"]
    ]


async def create_radius_profile(
    client: UnifiClient,
    name: str,
    auth_servers: list[dict],
    acct_servers: list[dict] | None = None,
    confirm: bool = False,
) -> dict:
    """Create a new RADIUS profile. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "auth_servers": auth_servers,
    }
    if acct_servers:
        payload["acct_servers"] = acct_servers

    if not confirm:
        return {
            "preview": True,
            "action": "create_radius_profile",
            "params": {"name": name, "auth_server_count": len(auth_servers)},
            "message": f"Will create RADIUS profile '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/radiusprofile",
        json=payload,
    )
    client.invalidate_cache("radius")
    return {"executed": True, "action": "create_radius_profile", "response": response}


async def update_radius_profile(
    client: UnifiClient,
    profile_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing RADIUS profile. Requires confirm=True after previewing."""
    if not confirm:
        # Strip shared secrets from preview to avoid leaking credentials
        safe_updates = {
            k: v for k, v in updates.items()
            if k not in ("auth_servers", "acct_servers")
        }
        if "auth_servers" in updates:
            safe_updates["auth_server_count"] = len(updates["auth_servers"])
        if "acct_servers" in updates:
            safe_updates["acct_server_count"] = len(updates["acct_servers"])
        return {
            "preview": True,
            "action": "update_radius_profile",
            "profile_id": profile_id,
            "updates": safe_updates,
            "message": f"Will update RADIUS profile {profile_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/radiusprofile/{profile_id}",
        json=updates,
    )
    client.invalidate_cache("radius")
    return {"executed": True, "action": "update_radius_profile", "response": response}


async def delete_radius_profile(client: UnifiClient, profile_id: str, confirm: bool = False) -> dict:
    """Delete a RADIUS profile. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_radius_profile",
            "profile_id": profile_id,
            "message": f"Will delete RADIUS profile {profile_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/radiusprofile/{profile_id}",
    )
    client.invalidate_cache("radius")
    return {"executed": True, "action": "delete_radius_profile", "response": response}


TOOLS = [list_radius_profiles, create_radius_profile, update_radius_profile, delete_radius_profile]
