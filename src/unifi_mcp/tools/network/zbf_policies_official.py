"""Create, update and delete zone-based firewall policies on the official Integration API.

Base path: /proxy/network/integration/v1/sites/{site_id}/firewall/policies (spec
10.6.106). Policy ids are Integration UUIDs from ``list_zbf_policies_v1``; zone
ids are UUIDs from ``list_zbf_zones``; network ids are Integration UUIDs.

Unlike the v2 ``create_zbf_policy``, these tools can match source and
destination IPs, subnets, ranges, networks and ports, the protocol, and the
connection state. Body shapes are built in zbf_policy_filters.py.

``loggingEnabled`` only feeds a remote syslog server. To observe a rule without
syslog, read its hit counter with ``list_zbf_policies`` (v2 ``hits`` and
``last_hit``; v2 ids differ from these UUIDs, so match the policy by name) or
check ``list_traffic_flows``.
"""

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.tools.network import zbf_policy_filters as f
from unifi_mcp.tools.network.zbf_official import (
    _changed_since_preview, _check_uuid, _executed, _fetch_policy, _not_found,
    _preview, _put_body, _remember_preview, _PUT_FIELDS,
)
from unifi_mcp.validation import validation_error

GROUP = "security"

TIER2_TOOLS = {
    "create_zbf_policy_v1": "zbf",
    "update_zbf_policy_v1": "zbf",
    "delete_zbf_policy_v1": "zbf",
}

_POLICIES = "/proxy/network/integration/v1/sites/{site_id}/firewall/policies"
_CACHE = "zbf"
_IMPACT = "Changes which traffic is allowed or blocked between these zones as soon as it is saved."


def _check_name(name) -> dict | None:
    if not isinstance(name, str) or not name.strip():
        return validation_error("name must be a non-empty string.")
    return None


def _check_bool_args(**values) -> dict | None:
    for field, value in values.items():
        if value is not None and not isinstance(value, bool):
            return validation_error(f"{field} must be a boolean.")
    return None


def _first_error(*parts) -> dict | None:
    return next((p for p in parts if f.is_error(p)), None)


def _not_user_defined(policy: dict, verb: str) -> dict | None:
    origin = (policy.get("metadata") or {}).get("origin")
    if origin == "USER_DEFINED":
        return None
    return validation_error(
        f"Only user-defined policies can be {verb}; this one has origin {origin or 'unknown'}."
    )


def _broad_allow_warning(body: dict) -> str | None:
    if body["action"]["type"] != "ALLOW":
        return None
    sides = (body["source"], body["destination"])
    no_filters = not any("trafficFilter" in side for side in sides)
    all_protocols = "protocolFilter" not in body["ipProtocolScope"]
    if no_filters and all_protocols:
        return "This rule allows all traffic between the two zones."
    return None


async def create_zbf_policy_v1(
    client: UnifiClient,
    name: str,
    source_zone_id: str,
    destination_zone_id: str,
    action: str = "ALLOW",
    allow_return_traffic: bool = False,
    source_ips: list[str] | None = None,
    source_network_ids: list[str] | None = None,
    source_ports: list[int | str] | None = None,
    destination_ips: list[str] | None = None,
    destination_network_ids: list[str] | None = None,
    destination_ports: list[int | str] | None = None,
    protocol: str = "all",
    ip_version: str = "IPV4_AND_IPV6",
    connection_states: list[str] | None = None,
    logging_enabled: bool = False,
    enabled: bool = True,
    description: str | None = None,
    confirm: bool = False,
) -> dict:
    """Create a ZBF policy with IP, network, port, protocol and state matching. Requires confirm=True after previewing.

    Zone ids come from list_zbf_zones; network ids are Integration UUIDs.
    *_ips entries are addresses, subnets (192.0.2.0/24) or ranges
    (192.0.2.10-192.0.2.20); use *_ips or *_network_ids per side, not both.
    *_ports entries are numbers or 'start-stop' ranges and need protocol tcp,
    udp or tcp_udp. protocol: all, tcp_udp, tcp, udp, icmp (icmp needs IPV4).
    connection_states: any of NEW, INVALID, ESTABLISHED, RELATED (omit for all);
    use ["NEW", "INVALID"] on blocks so replies still flow. allow_return_traffic
    only applies to ALLOW. The preview shows the exact request body.
    """
    if err := _check_name(name) or _check_bool_args(
        allow_return_traffic=allow_return_traffic, logging_enabled=logging_enabled, enabled=enabled,
    ):
        return err
    source = f.build_endpoint(
        source_zone_id, side="source", ips=source_ips, network_ids=source_network_ids, ports=source_ports,
    )
    destination = f.build_endpoint(
        destination_zone_id, side="destination", ips=destination_ips,
        network_ids=destination_network_ids, ports=destination_ports,
    )
    has_ports = f.endpoint_has_ports(source) or f.endpoint_has_ports(destination)
    scope = f.build_ip_scope(protocol, ip_version, has_ports=has_ports)
    built_action = f.build_action(action, allow_return_traffic=allow_return_traffic)
    states = f.check_connection_states(connection_states) if connection_states is not None else None
    if err := _first_error(source, destination, scope, built_action, states) or _first_error(
        f.check_ip_family(source, ip_version), f.check_ip_family(destination, ip_version),
    ):
        return err
    body = {
        "name": name.strip(), "enabled": enabled, "action": built_action,
        "source": source, "destination": destination, "ipProtocolScope": scope,
        "loggingEnabled": logging_enabled,
    } | ({"description": description} if description else {}) | (
        {"connectionStateFilter": states} if states else {}
    )
    if not confirm:
        warning = _broad_allow_warning(body)
        return _preview(
            "create_zbf_policy_v1",
            f"Will create ZBF policy '{body['name']}'. Call again with confirm=True to execute.",
            impact=_IMPACT, body=body, **({"warning": warning} if warning else {}),
        )
    response = await client.post(_POLICIES, json=body)
    client.invalidate_cache(_CACHE)
    return _executed("create_zbf_policy_v1", response, name=body["name"])


def _merged_side(current_side: dict, side: str, *, zone_id, ips, network_ids, ports, clear) -> dict | None:
    """New source or destination, or None to keep it.

    Each part merges on its own: IPs or networks replace the IP or network
    matcher, ports replace the port filter, and parts not passed are kept, so a
    narrowing change never drops an existing filter. clear starts from no filters.
    """
    if zone_id is None and ips is None and network_ids is None and ports is None and not clear:
        return None
    zone = zone_id if zone_id is not None else current_side.get("zoneId")
    old = {} if clear else (current_side.get("trafficFilter") or {})
    if ips is None and network_ids is None and ports is None:
        return {"zoneId": zone} | ({"trafficFilter": old} if old else {})
    fresh = f.build_endpoint(zone, side=side, ips=ips, network_ids=network_ids, ports=ports)
    if f.is_error(fresh):
        return fresh
    if not f.mergeable(old):
        return validation_error(
            f"The current {side} uses a {old.get('type')} filter or extra matching (such as a MAC "
            f"address or an exclusion list) that cannot be merged; pass clear_{side}_filters=True "
            "to replace it."
        )
    new = fresh.get("trafficFilter") or {}
    matcher = f.matcher_part(new) if (ips is not None or network_ids is not None) else f.matcher_part(old)
    port_filter = new.get("portFilter") if ports is not None else old.get("portFilter")
    return f.join_endpoint(zone, matcher, port_filter)


def _updated_action(current: dict, action, allow_return_traffic) -> dict | None:
    if action is None and allow_return_traffic is None:
        return None
    cur = current.get("action") or {}
    name = (action or cur.get("type", "")).upper()
    keep_flag = bool(cur.get("allowReturnTraffic", False)) if name == "ALLOW" else False
    return f.build_action(
        name, allow_return_traffic=keep_flag if allow_return_traffic is None else allow_return_traffic,
    )


def _updated_scope(current: dict, protocol, ip_version, *, ports_changed: bool, sides) -> dict | None:
    has_ports = any(f.endpoint_has_ports(side) for side in sides)
    cur_scope = current.get("ipProtocolScope") or {}
    if protocol is None and ip_version is None:
        if ports_changed and has_ports and not f.scope_allows_ports(cur_scope):
            return validation_error("Port matching needs protocol tcp, udp or tcp_udp; pass protocol as well.")
        return None
    if protocol is None:
        return validation_error("Pass protocol together with ip_version (the current one is not inferred).")
    return f.build_ip_scope(protocol, ip_version or cur_scope.get("ipVersion", "IPV4_AND_IPV6"), has_ports=has_ports)


def _check_update_args(policy_id, name, zone_ids, connection_states, clear_states, **flags) -> dict | None:
    if err := _check_uuid(policy_id, "policy_id") or _check_bool_args(**flags):
        return err
    if name is not None and (err := _check_name(name)):
        return err
    for field, zone in zone_ids.items():
        if zone is not None and (err := f.check_uuid(zone, field)):
            return err
    if connection_states is not None and clear_states:
        return validation_error("Pass connection_states or clear_connection_states, not both.")
    return None


def _comparable(body: dict, key: str):
    # The console keeps connection states in its own order; order carries no meaning.
    value = body.get(key)
    return sorted(value) if key == "connectionStateFilter" and isinstance(value, list) else value


def _plan_update(current: dict, args: dict) -> dict:
    """Return {"before", "after", "changed"} for an update, or a validation error."""
    before = _put_body(current)
    sides = {
        side: _merged_side(
            current.get(side) or {}, side, zone_id=args[f"{side}_zone_id"], ips=args[f"{side}_ips"],
            network_ids=args[f"{side}_network_ids"], ports=args[f"{side}_ports"],
            clear=args[f"clear_{side}_filters"],
        )
        for side in ("source", "destination")
    }
    action = _updated_action(current, args["action"], args["allow_return_traffic"])
    states = f.check_connection_states(args["connection_states"]) if args["connection_states"] is not None else None
    if err := _first_error(*sides.values(), action, states):
        return err
    final_sides = [sides[s] or before.get(s) or {} for s in ("source", "destination")]
    ports_changed = args["source_ports"] is not None or args["destination_ports"] is not None
    scope = _updated_scope(current, args["protocol"], args["ip_version"], ports_changed=ports_changed, sides=final_sides)
    if f.is_error(scope):
        return scope
    version = (scope or before.get("ipProtocolScope") or {}).get("ipVersion", "IPV4_AND_IPV6")
    rechecked = final_sides if args["ip_version"] is not None else [s for s in sides.values() if s]
    if err := _first_error(*(f.check_ip_family(side, version) for side in rechecked)):
        return err
    changes = {
        "name": args["name"].strip() if args["name"] is not None else None,
        "description": args["description"], "enabled": args["enabled"], "action": action,
        "source": sides["source"], "destination": sides["destination"], "ipProtocolScope": scope,
        "connectionStateFilter": states, "loggingEnabled": args["logging_enabled"],
    }
    after = before | {k: v for k, v in changes.items() if v is not None}
    if args["clear_connection_states"]:
        after = {k: v for k, v in after.items() if k != "connectionStateFilter"}
    changed = [k for k in _PUT_FIELDS if _comparable(before, k) != _comparable(after, k)]
    if not changed:
        return validation_error("No changes: every value passed matches the current policy, or none was passed.")
    return {"before": before, "after": after, "changed": changed}


async def update_zbf_policy_v1(
    client: UnifiClient,
    policy_id: str,
    name: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
    action: str | None = None,
    allow_return_traffic: bool | None = None,
    source_zone_id: str | None = None,
    source_ips: list[str] | None = None,
    source_network_ids: list[str] | None = None,
    source_ports: list[int | str] | None = None,
    clear_source_filters: bool = False,
    destination_zone_id: str | None = None,
    destination_ips: list[str] | None = None,
    destination_network_ids: list[str] | None = None,
    destination_ports: list[int | str] | None = None,
    clear_destination_filters: bool = False,
    protocol: str | None = None,
    ip_version: str | None = None,
    connection_states: list[str] | None = None,
    clear_connection_states: bool = False,
    logging_enabled: bool | None = None,
    confirm: bool = False,
) -> dict:
    """Change a user-defined ZBF policy by Integration UUID (GET, merge, PUT). Requires confirm=True after previewing.

    Only the arguments you pass change. On each side, *_ips or *_network_ids
    replace the IP or network matcher and *_ports replace the port filter;
    parts you do not pass are kept, and *_zone_id moves the side keeping its
    filters. clear_source_filters / clear_destination_filters start that side
    from no filters. Typical observe-then-enforce flip: action="BLOCK",
    connection_states=["NEW", "INVALID"]. clear_connection_states=True matches
    all states again. The preview shows the before and after bodies, and the
    confirm is refused if the policy changed after the preview.
    """
    args = dict(locals())
    del args["client"], args["confirm"]
    if err := _check_update_args(
        policy_id, name,
        {"source_zone_id": source_zone_id, "destination_zone_id": destination_zone_id},
        connection_states, clear_connection_states,
        enabled=enabled, allow_return_traffic=allow_return_traffic, logging_enabled=logging_enabled,
        clear_connection_states=clear_connection_states, clear_source_filters=clear_source_filters,
        clear_destination_filters=clear_destination_filters,
    ):
        return err
    current = await _fetch_policy(client, policy_id)
    if not current:
        return _not_found("policy", policy_id)
    if err := _not_user_defined(current, "changed"):
        return err
    plan = _plan_update(current, args)
    if f.is_error(plan):
        return plan
    if not confirm:
        _remember_preview("update_zbf_policy_v1", policy_id, current)
        return _preview(
            "update_zbf_policy_v1",
            f"Will update ZBF policy '{current.get('name', policy_id)}' ({', '.join(plan['changed'])}). "
            "Call again with confirm=True to execute.",
            impact=_IMPACT, policy_id=policy_id, changed_fields=plan["changed"],
            before=plan["before"], after=plan["after"],
        )
    if err := _changed_since_preview("update_zbf_policy_v1", policy_id, current):
        return err
    response = await client.put(f"{_POLICIES}/{policy_id}", json=plan["after"])
    client.invalidate_cache(_CACHE)
    return _executed("update_zbf_policy_v1", response, policy_id=policy_id, changed_fields=plan["changed"])


async def delete_zbf_policy_v1(client: UnifiClient, policy_id: str, confirm: bool = False) -> dict:
    """Delete a user-defined ZBF policy by Integration UUID. Requires confirm=True after previewing.

    The preview names the policy so the right one is removed. System-defined
    policies are refused.
    """
    if err := _check_uuid(policy_id, "policy_id"):
        return err
    current = await _fetch_policy(client, policy_id)
    if not current:
        return _not_found("policy", policy_id)
    if err := _not_user_defined(current, "deleted"):
        return err
    name = current.get("name", "")
    if not confirm:
        return _preview(
            "delete_zbf_policy_v1",
            f"Will delete ZBF policy '{name}'. Call again with confirm=True to execute.",
            impact=_IMPACT, policy_id=policy_id, name=name,
        )
    response = await client.delete(f"{_POLICIES}/{policy_id}")
    client.invalidate_cache(_CACHE)
    return _executed("delete_zbf_policy_v1", response, expect_body=False, policy_id=policy_id, name=name)


TOOLS = [create_zbf_policy_v1, update_zbf_policy_v1, delete_zbf_policy_v1]
