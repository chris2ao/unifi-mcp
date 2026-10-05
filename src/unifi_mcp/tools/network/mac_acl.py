"""MAC ACL tools: list, add, delete filter rules, and read/change rule order.

Rules use the V2 API: /proxy/network/v2/api/site/{site}/acl-rules
Ordering uses the official Integration API:
/proxy/network/integration/v1/sites/{site_id}/acl-rules/ordering
"""

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError
from unifi_mcp.validation import check_id, validation_error

TIER2_TOOLS: dict[str, str] = {
    "add_mac_filter": "mac_acl",
    "delete_mac_filter": "mac_acl",
    "reorder_acl_rules": "mac_acl",
}

_ORDERING = "/proxy/network/integration/v1/sites/{site_id}/acl-rules/ordering"


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


def _extract_order(response: object) -> list[str]:
    if isinstance(response, dict):
        ids = response.get("orderedAclRuleIds")
        if ids is None and isinstance(response.get("data"), dict):
            ids = response["data"].get("orderedAclRuleIds")
    else:
        ids = response
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []


async def get_acl_rule_order(client: UnifiClient) -> dict:
    """Get the evaluation order of user-defined ACL rules (first id is evaluated first)."""
    response = await client.get(_ORDERING, cache_category="mac_acl", cache_ttl=30.0)
    ids = _extract_order(response)
    return {"ordered_rule_ids": ids, "count": len(ids)}


def _validate_new_order(ordered_rule_ids: object, current: list[str]) -> dict | None:
    if not isinstance(ordered_rule_ids, list) or not ordered_rule_ids:
        return validation_error("ordered_rule_ids must be a non-empty list of ACL rule ids.")
    for rule_id in ordered_rule_ids:
        err = check_id(rule_id, "ordered_rule_ids item")
        if err:
            return err
    if len(set(ordered_rule_ids)) != len(ordered_rule_ids):
        return validation_error("ordered_rule_ids contains duplicate ids.")
    missing = [i for i in current if i not in ordered_rule_ids]
    unknown = [i for i in ordered_rule_ids if i not in current]
    if missing or unknown:
        return validation_error(
            "ordered_rule_ids must contain exactly the current rule ids. "
            f"Missing: {missing or 'none'}. Unknown: {unknown or 'none'}."
        )
    return None


async def reorder_acl_rules(
    client: UnifiClient, ordered_rule_ids: list[str], confirm: bool = False
) -> dict:
    """Set the evaluation order of ACL rules. ordered_rule_ids must list every current rule id exactly once.

    Order decides which rule wins when several match, so a wrong order can
    block or expose devices. Use get_acl_rule_order first. Requires
    confirm=True after previewing.
    """
    try:
        current = _extract_order(await client.get(_ORDERING))
    except UnifiError as e:
        return e.to_dict()
    err = _validate_new_order(ordered_rule_ids, current)
    if err:
        return err
    new_order = list(ordered_rule_ids)
    if not confirm:
        return {
            "preview": True,
            "action": "reorder_acl_rules",
            "current_order": current,
            "new_order": new_order,
            "changed": new_order != current,
            "impact": (
                "Reordering ACL rules changes which rule is evaluated first. Rules that "
                "match the same traffic may now allow or block devices differently."
            ),
            "message": "Will reorder ACL rules. Call again with confirm=True to execute.",
        }
    response = await client.put(_ORDERING, json={"orderedAclRuleIds": new_order})
    client.invalidate_cache("mac_acl")
    applied = _extract_order(response) or _extract_order(await client.get(_ORDERING))
    if applied != new_order:
        return {
            "executed": False, "action": "reorder_acl_rules", "applied_order": applied,
            "response": response,
            "message": "The console did not apply the requested order. Check get_acl_rule_order.",
        }
    return {"executed": True, "action": "reorder_acl_rules", "new_order": applied, "response": response}


TOOLS = [
    list_mac_filter, add_mac_filter, delete_mac_filter,
    get_acl_rule_order, reorder_acl_rules,
]
