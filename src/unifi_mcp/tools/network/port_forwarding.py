"""Port forwarding tools: list, create, update, delete.

Uses V1 REST API per the endpoint catalog:
/proxy/network/api/s/{site}/rest/portforward

Schema note: the controller stores the forward target IP in the `fwd` field,
not `fwd_ip`. Reads must surface `fwd`; writes must send `fwd`. On UniFi
Network 9.x the `/rest/portforward/{id}` PUT ignores a partial body (returns
HTTP 200 with an empty `data` array), so updates GET the full rule, merge, and
PUT the complete object.
"""

from unifi_mcp.auth.client import UnifiClient


def _display_rule(r: dict) -> dict:
    """Map a raw controller port-forward record to the tool's display shape.

    The controller field for the forward target is `fwd`; older/renamed schemas
    used `fwd_ip`. Read `fwd` first and fall back so both shapes surface a value.
    """
    return {
        "id": r.get("_id", ""),
        "name": r.get("name", ""),
        "fwd_ip": r.get("fwd") or r.get("fwd_ip", ""),
        "fwd_port": r.get("fwd_port", ""),
        "dst_port": r.get("dst_port", ""),
        "proto": r.get("proto", ""),
        "pfwd_interface": r.get("pfwd_interface", ""),
        "enabled": r.get("enabled", True),
    }


async def list_port_forwards(client: UnifiClient) -> list[dict]:
    """List all port forwarding rules."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/portforward",
        cache_category="port_forwarding", cache_ttl=30.0,
    )
    return [_display_rule(r) for r in response["data"]]


async def _fetch_rule(client: UnifiClient, rule_id: str) -> dict | None:
    """Fetch the full raw port-forward rule object, or None if not found.

    Uses an uncached GET because callers are about to mutate the rule and need
    the current controller state to build a complete PUT body.
    """
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/rest/portforward/{rule_id}"
    )
    data = response.get("data", []) if isinstance(response, dict) else []
    return data[0] if data else None


async def create_port_forward(
    client: UnifiClient,
    name: str,
    fwd_ip: str,
    fwd_port: str,
    dst_port: str,
    proto: str = "tcp",
    enabled: bool = True,
    pfwd_interface: str | None = None,
    confirm: bool = False,
) -> dict:
    """Create a new port forwarding rule. Requires confirm=True after previewing.

    pfwd_interface binds the rule to a WAN interface on dual-WAN setups
    (e.g. "wan", "wan2", "both"). Omit to use the controller default.
    """
    payload = {
        "name": name,
        "fwd": fwd_ip,
        "fwd_port": fwd_port,
        "dst_port": dst_port,
        "proto": proto,
        "enabled": enabled,
    }
    if pfwd_interface is not None:
        payload["pfwd_interface"] = pfwd_interface

    if not confirm:
        return {
            "preview": True,
            "action": "create_port_forward",
            "params": payload,
            "message": f"Will create port forward '{name}' ({proto} :{dst_port} -> {fwd_ip}:{fwd_port}). Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/portforward",
        json=payload,
    )
    client.invalidate_cache("port_forwarding")
    return {"executed": True, "action": "create_port_forward", "response": response}


async def update_port_forward(
    client: UnifiClient,
    rule_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing port forwarding rule. Requires confirm=True after previewing.

    The controller ignores a partial PUT body, so this fetches the full rule,
    merges `updates` onto it, and PUTs the complete object. Pass the forward
    target as either `fwd` or `fwd_ip`; both normalize to the controller's `fwd`
    field. WAN binding can be changed via `pfwd_interface` in `updates`.
    """
    # Normalize the convenience alias to the controller field.
    normalized = dict(updates)
    if "fwd_ip" in normalized:
        normalized["fwd"] = normalized.pop("fwd_ip")

    if not confirm:
        return {
            "preview": True,
            "action": "update_port_forward",
            "rule_id": rule_id,
            "updates": normalized,
            "message": f"Will update port forward {rule_id}. Call again with confirm=True to execute.",
        }

    existing = await _fetch_rule(client, rule_id)
    if existing is None:
        return {
            "executed": False,
            "action": "update_port_forward",
            "rule_id": rule_id,
            "error": f"Port forward rule {rule_id} not found.",
        }

    merged = {**existing, **normalized}

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/portforward/{rule_id}",
        json=merged,
    )
    client.invalidate_cache("port_forwarding")

    # A successful update echoes the updated rule in `data`. An empty array means
    # the controller accepted the request (HTTP 200) but persisted nothing, so
    # report that as a failure rather than a silent no-op.
    data = response.get("data", []) if isinstance(response, dict) else []
    if not data:
        return {
            "executed": False,
            "action": "update_port_forward",
            "rule_id": rule_id,
            "response": response,
            "error": "Controller returned an empty data array; the update did not persist.",
        }

    return {"executed": True, "action": "update_port_forward", "response": response}


async def delete_port_forward(client: UnifiClient, rule_id: str, confirm: bool = False) -> dict:
    """Delete a port forwarding rule. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_port_forward",
            "rule_id": rule_id,
            "message": f"Will delete port forward {rule_id}. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/portforward/{rule_id}",
    )
    client.invalidate_cache("port_forwarding")
    return {"executed": True, "action": "delete_port_forward", "response": response}


TOOLS = [list_port_forwards, create_port_forward, update_port_forward, delete_port_forward]
