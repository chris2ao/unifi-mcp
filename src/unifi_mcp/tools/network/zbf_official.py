"""Zone-Based Firewall tools built on the official Network Integration API.

Base path: /proxy/network/integration/v1/sites/{site_id}/firewall (spec 10.6.106).

ID types (verified live on Network 10.6.106): Integration API policy ids are
UUIDs and are NOT the same as the "_id" values returned by the v2
firewall-policies endpoint used by ``list_zbf_policies`` (those are Mongo style
strings, and no field links the two). Every policy tool in this module needs the
UUID from ``list_zbf_policies_v1``. Zone ids from ``list_zbf_zones`` are already
Integration UUIDs.

Custom zone create/update/delete tools live in zbf_zones_official.py.

Spec notes: the PATCH body only accepts ``loggingEnabled``, so toggling
``enabled`` is done as GET-merge-PUT (PUT body is the "create or update"
schema). Policy ordering is split into ``beforeSystemDefined`` and
``afterSystemDefined`` lists of user-defined policy ids per zone pair.
"""

import re

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.validation import validation_error

GROUP = "security"

TIER2_TOOLS = {
    "toggle_zbf_policy": "zbf",
    "set_zbf_policy_logging": "zbf",
    "reorder_zbf_policies": "zbf",
}

_BASE = "/proxy/network/integration/v1/sites/{site_id}/firewall"
_CACHE = "zbf"
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
# Fields accepted by the "create or update firewall policy" PUT body.
_PUT_FIELDS = (
    "enabled", "name", "description", "action", "source", "destination",
    "ipProtocolScope", "connectionStateFilter", "ipsecFilter", "loggingEnabled",
    "schedule",
)


def _check_uuid(value, field: str) -> dict | None:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        return validation_error(
            f"{field} must be an Integration API UUID (for policies, use the id from "
            "list_zbf_policies_v1; v2 '_id' values from list_zbf_policies are a "
            f"different id type and are not accepted). Got: {value!r}."
        )
    return None


def _check_bool(value, field: str) -> dict | None:
    return None if isinstance(value, bool) else validation_error(f"{field} must be a boolean.")


def _first_error(*errors: dict | None) -> dict | None:
    return next((e for e in errors if e), None)


def _unwrap(response) -> dict:
    """Return a single object from a bare object or {"data": obj | [obj]}."""
    if isinstance(response, dict) and "data" in response and "id" not in response:
        data = response["data"]
        response = data[0] if isinstance(data, list) and data else data
    return response if isinstance(response, dict) else {}


def _not_found(kind: str, ident: str) -> dict:
    return {
        "error": True, "category": "NOT_FOUND",
        "message": f"No ZBF {kind} found with id '{ident}'.", f"{kind}_id": ident,
    }


def _format_policy(p: dict, detail: bool = False) -> dict:
    out = {
        "id": p.get("id", ""),
        "name": p.get("name", ""),
        "description": p.get("description", ""),
        "enabled": p.get("enabled", True),
        "index": p.get("index", 0),
        "action": (p.get("action") or {}).get("type", ""),
        "source_zone_id": (p.get("source") or {}).get("zoneId", ""),
        "destination_zone_id": (p.get("destination") or {}).get("zoneId", ""),
        "ip_protocol_scope": p.get("ipProtocolScope"),
        "logging_enabled": p.get("loggingEnabled", False),
        "origin": (p.get("metadata") or {}).get("origin", ""),
    }
    if detail:
        out.update({
            "action_detail": p.get("action", {}),
            "source": p.get("source", {}),
            "destination": p.get("destination", {}),
            "connection_state_filter": p.get("connectionStateFilter"),
            "ipsec_filter": p.get("ipsecFilter"),
            "schedule": p.get("schedule"),
        })
    return out


def _preview(action: str, message: str, impact: str | None = None, **params) -> dict:
    out = {"preview": True, "action": action, **params, "message": message}
    if impact:
        out["impact"] = impact
    return out


def _executed(action: str, response, expect_body: bool = True, **extra) -> dict:
    if expect_body and not response:
        return {
            "executed": False, "action": action, **extra, "response": response,
            "message": (
                "The console returned HTTP 200 with an empty body, which usually means "
                "the request was ignored. Verify the target and retry."
            ),
        }
    return {"executed": True, "action": action, **extra, "response": response}


async def _fetch_policy(client: UnifiClient, policy_id: str) -> dict:
    return _unwrap(await client.get(f"{_BASE}/policies/{policy_id}"))


async def get_zbf_policy(client: UnifiClient, policy_id: str) -> dict:
    """Get one zone-based firewall policy by Integration API id (UUID from list_zbf_policies_v1).

    Returns action, source/destination zone and traffic filters, logging, schedule
    and origin. Do not pass v2 '_id' values from list_zbf_policies; they are a
    different id type.
    """
    if err := _check_uuid(policy_id, "policy_id"):
        return err
    response = await client.get(
        f"{_BASE}/policies/{policy_id}", cache_category=_CACHE, cache_ttl=30.0,
    )
    policy = _unwrap(response)
    if not policy:
        return _not_found("policy", policy_id)
    return _format_policy(policy, detail=True)


async def list_zbf_policies_v1(
    client: UnifiClient,
    source_zone_id: str | None = None,
    destination_zone_id: str | None = None,
    filter: str | None = None,  # noqa: A002 (matches the API parameter name)
) -> list[dict]:
    """List ZBF policies via the official API (all pages), with Integration UUID ids.

    Use this to get the policy ids needed by get_zbf_policy, toggle_zbf_policy,
    set_zbf_policy_logging and reorder_zbf_policies. Optional source_zone_id and
    destination_zone_id (zone UUIDs from list_zbf_zones) narrow the result;
    filter is the official API filter expression passed through unchanged.
    """
    if err := _first_error(
        _check_uuid(source_zone_id, "source_zone_id") if source_zone_id else None,
        _check_uuid(destination_zone_id, "destination_zone_id") if destination_zone_id else None,
        validation_error("filter must be a string expression.")
        if filter is not None and not isinstance(filter, str) else None,
    ):
        return [err]
    items = await client.get_all_pages(
        f"{_BASE}/policies", filter=filter, cache_category=_CACHE, cache_ttl=30.0,
    )
    rows = [_format_policy(p) for p in items if isinstance(p, dict)]
    return [
        r for r in rows
        if (not source_zone_id or r["source_zone_id"] == source_zone_id)
        and (not destination_zone_id or r["destination_zone_id"] == destination_zone_id)
    ]


async def toggle_zbf_policy(
    client: UnifiClient,
    policy_id: str,
    enabled: bool,
    confirm: bool = False,
) -> dict:
    """Enable or disable a ZBF policy by Integration UUID. Requires confirm=True after previewing.

    The PATCH endpoint only accepts loggingEnabled, so this reads the policy and
    sends the merged body with PUT. Disabling a policy can open or close traffic
    paths between zones immediately.
    """
    if err := _first_error(_check_uuid(policy_id, "policy_id"), _check_bool(enabled, "enabled")):
        return err
    current = await _fetch_policy(client, policy_id)
    if not current:
        return _not_found("policy", policy_id)
    if not confirm:
        return _preview(
            "toggle_zbf_policy",
            f"Will set ZBF policy '{current.get('name', policy_id)}' enabled={enabled}. "
            "Call again with confirm=True to execute.",
            impact="Changes which traffic is allowed or blocked between zones right away.",
            policy_id=policy_id, name=current.get("name", ""),
            current_enabled=current.get("enabled"), enabled=enabled,
        )
    body = {k: current[k] for k in _PUT_FIELDS if k in current} | {"enabled": enabled}
    response = await client.put(f"{_BASE}/policies/{policy_id}", json=body)
    client.invalidate_cache(_CACHE)
    return _executed("toggle_zbf_policy", response, policy_id=policy_id, enabled=enabled)


async def set_zbf_policy_logging(
    client: UnifiClient,
    policy_id: str,
    logging_enabled: bool,
    confirm: bool = False,
) -> dict:
    """Turn syslog logging on or off for a ZBF policy (PATCH loggingEnabled). Requires confirm=True after previewing.

    policy_id is the Integration UUID from list_zbf_policies_v1. Logging only
    affects syslog output, not which traffic is allowed.
    """
    if err := _first_error(
        _check_uuid(policy_id, "policy_id"), _check_bool(logging_enabled, "logging_enabled"),
    ):
        return err
    if not confirm:
        return _preview(
            "set_zbf_policy_logging",
            f"Will set loggingEnabled={logging_enabled} on ZBF policy {policy_id}. "
            "Call again with confirm=True to execute.",
            policy_id=policy_id, logging_enabled=logging_enabled,
        )
    response = await client.patch(
        f"{_BASE}/policies/{policy_id}", json={"loggingEnabled": logging_enabled},
    )
    client.invalidate_cache(_CACHE)
    return _executed(
        "set_zbf_policy_logging", response,
        policy_id=policy_id, logging_enabled=logging_enabled,
    )


def _ordering_lists(response) -> tuple[list[str], list[str]]:
    ordered = _unwrap(response)
    ordered = ordered.get("orderedFirewallPolicyIds", ordered)
    return (
        list(ordered.get("beforeSystemDefined") or []),
        list(ordered.get("afterSystemDefined") or []),
    )


async def _fetch_ordering(client: UnifiClient, source_zone_id: str, destination_zone_id: str):
    response = await client.get(
        f"{_BASE}/policies/ordering",
        params={
            "sourceFirewallZoneId": source_zone_id,
            "destinationFirewallZoneId": destination_zone_id,
        },
    )
    return _ordering_lists(response)


async def get_zbf_policy_order(
    client: UnifiClient, source_zone_id: str, destination_zone_id: str,
) -> dict:
    """Get the user-defined policy order for one source/destination zone pair.

    Both ids are zone UUIDs from list_zbf_zones. Returns policy ids (UUIDs) in
    evaluation order, split into before_system_defined (evaluated ahead of the
    built-in policies) and after_system_defined.
    """
    if err := _first_error(
        _check_uuid(source_zone_id, "source_zone_id"),
        _check_uuid(destination_zone_id, "destination_zone_id"),
    ):
        return err
    before, after = await _fetch_ordering(client, source_zone_id, destination_zone_id)
    return {
        "source_zone_id": source_zone_id,
        "destination_zone_id": destination_zone_id,
        "before_system_defined": before,
        "after_system_defined": after,
        "total": len(before) + len(after),
    }


def _plan_reorder(
    current: tuple[list[str], list[str]], ordered: list[str], after_ids: list[str] | None,
) -> tuple[list[str], list[str]] | dict:
    """Return the new (before, after) lists, or a validation error dict."""
    cur_before, cur_after = current
    if after_ids is None:
        new_before, new_after = ordered[: len(cur_before)], ordered[len(cur_before):]
    else:
        new_before, new_after = list(ordered), list(after_ids)
    combined = [*new_before, *new_after]
    expected = {*cur_before, *cur_after}
    if len(combined) != len(set(combined)) or set(combined) != expected:
        return validation_error(
            "The supplied ids must match the current policy set for this zone pair "
            "exactly (no duplicates, none missing, none extra). "
            f"Missing: {sorted(expected - set(combined))}. "
            f"Unexpected: {sorted(set(combined) - expected)}."
        )
    return new_before, new_after


async def reorder_zbf_policies(
    client: UnifiClient,
    source_zone_id: str,
    destination_zone_id: str,
    ordered_policy_ids: list[str],
    after_system_defined_ids: list[str] | None = None,
    confirm: bool = False,
) -> dict:
    """Reorder user-defined ZBF policies for a zone pair. Requires confirm=True after previewing.

    ordered_policy_ids is the complete desired order of policy UUIDs (from
    get_zbf_policy_order); it must contain exactly the current set. Without
    after_system_defined_ids the before/after-system-defined section sizes are
    kept; pass after_system_defined_ids to set that section explicitly (then
    ordered_policy_ids is the before-system-defined section).
    """
    if err := _first_error(
        _check_uuid(source_zone_id, "source_zone_id"),
        _check_uuid(destination_zone_id, "destination_zone_id"),
        _check_id_list(ordered_policy_ids, "ordered_policy_ids"),
        _check_id_list(after_system_defined_ids, "after_system_defined_ids")
        if after_system_defined_ids is not None else None,
    ):
        return err
    current = await _fetch_ordering(client, source_zone_id, destination_zone_id)
    plan = _plan_reorder(current, ordered_policy_ids, after_system_defined_ids)
    if isinstance(plan, dict):
        return plan
    new_before, new_after = plan
    before_state = {"before_system_defined": current[0], "after_system_defined": current[1]}
    after_state = {"before_system_defined": new_before, "after_system_defined": new_after}
    if not confirm:
        return _preview(
            "reorder_zbf_policies",
            "Will reorder ZBF policies for this zone pair. "
            "Call again with confirm=True to execute.",
            impact="Policy order decides which rule matches first; reordering can "
            "immediately change which traffic between these zones is allowed or blocked.",
            source_zone_id=source_zone_id, destination_zone_id=destination_zone_id,
            order_before=before_state, order_after=after_state,
            changed=before_state != after_state,
        )
    body = {"orderedFirewallPolicyIds": {
        "beforeSystemDefined": new_before, "afterSystemDefined": new_after,
    }}
    query = f"sourceFirewallZoneId={source_zone_id}&destinationFirewallZoneId={destination_zone_id}"
    response = await client.put(f"{_BASE}/policies/ordering?{query}", json=body)
    client.invalidate_cache(_CACHE)
    return _executed(
        "reorder_zbf_policies", response,
        source_zone_id=source_zone_id, destination_zone_id=destination_zone_id,
    )


def _check_id_list(value, field: str) -> dict | None:
    if not isinstance(value, list):
        return validation_error(f"{field} must be a list of policy UUIDs.")
    for item in value:
        if err := _check_uuid(item, field):
            return err
    return None


TOOLS = [
    get_zbf_policy, list_zbf_policies_v1, toggle_zbf_policy, set_zbf_policy_logging,
    get_zbf_policy_order, reorder_zbf_policies,
]
