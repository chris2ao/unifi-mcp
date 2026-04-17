"""Legacy firewall tools: rules CRUD, groups CRUD, reorder."""

from unifi_mcp.auth.client import UnifiClient


async def list_firewall_rules(client: UnifiClient) -> list[dict]:
    """List all legacy firewall rules."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/firewallrule",
        cache_category="firewall", cache_ttl=30.0,
    )
    return [
        {
            "id": r.get("_id", ""),
            "name": r.get("name", ""),
            "enabled": r.get("enabled", True),
            "action": r.get("action", ""),
            "protocol": r.get("protocol", "all"),
            "src_address": r.get("src_address", ""),
            "dst_address": r.get("dst_address", ""),
            "dst_port": r.get("dst_port", ""),
            "rule_index": r.get("rule_index", 0),
            "ruleset": r.get("ruleset", ""),
        }
        for r in response["data"]
    ]


async def create_firewall_rule(
    client: UnifiClient,
    name: str,
    action: str,
    protocol: str = "all",
    ruleset: str = "LAN_IN",
    src_address: str = "",
    dst_address: str = "",
    src_port: str = "",
    dst_port: str = "",
    rule_index: int = 2000,
    enabled: bool = True,
    confirm: bool = False,
) -> dict:
    """Create a new firewall rule. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "enabled": enabled,
        "action": action,
        "protocol": protocol,
        "ruleset": ruleset,
        "rule_index": rule_index,
    }
    if src_address:
        payload["src_address"] = src_address
    if dst_address:
        payload["dst_address"] = dst_address
    if src_port:
        payload["src_port"] = src_port
    if dst_port:
        payload["dst_port"] = dst_port

    if not confirm:
        return {
            "preview": True,
            "action": "create_firewall_rule",
            "params": payload,
            "message": f"Will create firewall rule '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/firewallrule",
        json=payload,
    )
    client.invalidate_cache("firewall")
    return {"executed": True, "action": "create_firewall_rule", "response": response}


async def update_firewall_rule(
    client: UnifiClient,
    rule_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing firewall rule. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "update_firewall_rule",
            "rule_id": rule_id,
            "updates": updates,
            "message": f"Will update firewall rule {rule_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/firewallrule/{rule_id}",
        json=updates,
    )
    client.invalidate_cache("firewall")
    return {"executed": True, "action": "update_firewall_rule", "response": response}


async def delete_firewall_rule(client: UnifiClient, rule_id: str, confirm: bool = False) -> dict:
    """Delete a firewall rule. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_firewall_rule",
            "rule_id": rule_id,
            "message": f"Will delete firewall rule {rule_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/firewallrule/{rule_id}",
    )
    client.invalidate_cache("firewall")
    return {"executed": True, "action": "delete_firewall_rule", "response": response}


async def reorder_firewall_rules(
    client: UnifiClient,
    rule_id: str,
    new_index: int,
    confirm: bool = False,
) -> dict:
    """Change a firewall rule's position by updating its rule_index. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "reorder_firewall_rules",
            "rule_id": rule_id,
            "new_index": new_index,
            "message": f"Will move firewall rule {rule_id} to index {new_index}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/firewallrule/{rule_id}",
        json={"rule_index": new_index},
    )
    client.invalidate_cache("firewall")
    return {"executed": True, "action": "reorder_firewall_rules", "response": response}


async def list_firewall_groups(client: UnifiClient) -> list[dict]:
    """List all firewall groups (address groups and port groups)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/firewallgroup",
        cache_category="firewall", cache_ttl=30.0,
    )
    return [
        {
            "id": g.get("_id", ""),
            "name": g.get("name", ""),
            "group_type": g.get("group_type", ""),
            "group_members": g.get("group_members", []),
        }
        for g in response["data"]
    ]


async def create_firewall_group(
    client: UnifiClient,
    name: str,
    group_type: str,
    members: list[str],
    confirm: bool = False,
) -> dict:
    """Create a new firewall group. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "group_type": group_type,
        "group_members": members,
    }

    if not confirm:
        return {
            "preview": True,
            "action": "create_firewall_group",
            "params": payload,
            "message": f"Will create firewall group '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/firewallgroup",
        json=payload,
    )
    client.invalidate_cache("firewall")
    return {"executed": True, "action": "create_firewall_group", "response": response}


async def delete_firewall_group(client: UnifiClient, group_id: str, confirm: bool = False) -> dict:
    """Delete a firewall group. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_firewall_group",
            "group_id": group_id,
            "message": f"Will delete firewall group {group_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/firewallgroup/{group_id}",
    )
    client.invalidate_cache("firewall")
    return {"executed": True, "action": "delete_firewall_group", "response": response}


TOOLS = [
    list_firewall_rules, create_firewall_rule, update_firewall_rule,
    delete_firewall_rule, reorder_firewall_rules, list_firewall_groups,
    create_firewall_group, delete_firewall_group,
]
