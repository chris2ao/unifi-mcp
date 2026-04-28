"""Traffic Rules tools: list, get, create, update, delete, toggle.

Uses the V2 API:
/proxy/network/v2/api/site/{site}/trafficrules

Traffic Rules let you allow or block traffic for specific networks, clients,
or devices. They match on internet/domain/IP/region/app+category/local-network
targets and support schedules and bandwidth limits. Common use cases include
forcing all DNS through a local resolver (block port 53 to internet) and
time-of-day kid controls.

The payload is rich and version-dependent, so create/update accept a free-form
``rule`` / ``updates`` dict. Callers should fetch a similar existing rule via
``list_traffic_rules`` to discover the current schema before constructing a
new one.
"""

from unifi_mcp.auth.client import UnifiClient


def _format_rule(r: dict) -> dict:
    # UniFi's v2 trafficrules schema uses ``description`` for the rule label and
    # does not support port-level filtering. The fields below are surfaced as
    # they are returned by the controller; absent fields default to empty.
    return {
        "id": r.get("_id", ""),
        "description": r.get("description", ""),
        "action": r.get("action", ""),
        "enabled": r.get("enabled", True),
        "matching_target": r.get("matching_target", ""),
        "target_devices": r.get("target_devices", []),
        "ip_addresses": r.get("ip_addresses", []),
        "ip_ranges": r.get("ip_ranges", []),
        "domains": r.get("domains", []),
        "regions": r.get("regions", []),
        "app_category_ids": r.get("app_category_ids", []),
        "app_ids": r.get("app_ids", []),
        "network_ids": r.get("network_ids", []),
        "schedule": r.get("schedule", {}),
        "bandwidth_limit": r.get("bandwidth_limit", {}),
    }


async def _fetch_rule(client: UnifiClient, rule_id: str) -> dict | None:
    """Fetch a single rule by scanning the collection (GET-by-id is 405)."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/trafficrules",
    )
    rules = response if isinstance(response, list) else response.get("data", [])
    for r in rules:
        if isinstance(r, dict) and r.get("_id") == rule_id:
            return r
    return None


async def list_traffic_rules(client: UnifiClient) -> list[dict]:
    """List all Traffic Rules."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/trafficrules",
        cache_category="traffic_rules", cache_ttl=30.0,
    )
    rules = response if isinstance(response, list) else response.get("data", [])
    return [_format_rule(r) for r in rules]


async def get_traffic_rule(client: UnifiClient, rule_id: str) -> dict:
    """Get a specific Traffic Rule by ID.

    Note: the UniFi v2 trafficrules endpoint does not support GET by id (returns
    405). This implementation fetches the collection and filters locally.
    """
    rule = await _fetch_rule(client, rule_id)
    if rule is None:
        return {
            "error": True,
            "category": "NOT_FOUND",
            "message": f"No traffic rule found with id '{rule_id}'",
            "rule_id": rule_id,
        }
    return _format_rule(rule)


async def create_traffic_rule(
    client: UnifiClient,
    rule: dict,
    confirm: bool = False,
) -> dict:
    """Create a new Traffic Rule. Pass the full rule body as ``rule``.

    Required fields typically include: ``name``, ``action`` (ALLOW/BLOCK),
    ``matching_target`` (INTERNET/DOMAIN/IP/REGION/APP_CATEGORY/INTERNAL),
    ``target_devices`` (list of {"type", "network_id"|"client_mac"}), and
    ``schedule`` ({"mode": "ALWAYS"} or a recurring spec). Requires
    ``confirm=True`` after previewing.
    """
    if not confirm:
        return {
            "preview": True,
            "action": "create_traffic_rule",
            "rule": rule,
            "message": (
                f"Will create traffic rule '{rule.get('name', '?')}' "
                f"({rule.get('action', '?')}). Call again with confirm=True to execute."
            ),
        }

    response = await client.post(
        "/proxy/network/v2/api/site/{site}/trafficrules",
        json=rule,
    )
    client.invalidate_cache("traffic_rules")
    return {"executed": True, "action": "create_traffic_rule", "response": response}


async def update_traffic_rule(
    client: UnifiClient,
    rule_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing Traffic Rule. Requires ``confirm=True`` after previewing.

    UniFi's PUT replaces the rule body, so callers should fetch the current
    rule with ``get_traffic_rule`` and merge changes into the full payload.
    """
    if not confirm:
        return {
            "preview": True,
            "action": "update_traffic_rule",
            "rule_id": rule_id,
            "updates": updates,
            "message": (
                f"Will update traffic rule {rule_id}. "
                "Call again with confirm=True to execute."
            ),
        }

    response = await client.put(
        f"/proxy/network/v2/api/site/{{site}}/trafficrules/{rule_id}",
        json=updates,
    )
    client.invalidate_cache("traffic_rules")
    return {"executed": True, "action": "update_traffic_rule", "response": response}


async def delete_traffic_rule(
    client: UnifiClient,
    rule_id: str,
    confirm: bool = False,
) -> dict:
    """Delete a Traffic Rule. Requires ``confirm=True`` after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_traffic_rule",
            "rule_id": rule_id,
            "message": (
                f"Will delete traffic rule {rule_id}. "
                "This is irreversible. Call again with confirm=True to execute."
            ),
        }

    response = await client.delete(
        f"/proxy/network/v2/api/site/{{site}}/trafficrules/{rule_id}",
    )
    client.invalidate_cache("traffic_rules")
    return {"executed": True, "action": "delete_traffic_rule", "response": response}


async def toggle_traffic_rule(
    client: UnifiClient,
    rule_id: str,
    enabled: bool,
    confirm: bool = False,
) -> dict:
    """Enable or disable a Traffic Rule without altering its other fields."""
    if not confirm:
        return {
            "preview": True,
            "action": "toggle_traffic_rule",
            "rule_id": rule_id,
            "enabled": enabled,
            "message": (
                f"Will set traffic rule {rule_id} enabled={enabled}. "
                "Call again with confirm=True to execute."
            ),
        }

    body = await _fetch_rule(client, rule_id)
    if body is None:
        return {
            "error": True,
            "category": "NOT_FOUND",
            "message": f"No traffic rule found with id '{rule_id}'",
            "rule_id": rule_id,
        }
    body["enabled"] = enabled

    response = await client.put(
        f"/proxy/network/v2/api/site/{{site}}/trafficrules/{rule_id}",
        json=body,
    )
    client.invalidate_cache("traffic_rules")
    return {"executed": True, "action": "toggle_traffic_rule", "response": response}


TOOLS = [
    list_traffic_rules,
    get_traffic_rule,
    create_traffic_rule,
    update_traffic_rule,
    delete_traffic_rule,
    toggle_traffic_rule,
]
