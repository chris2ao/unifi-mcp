"""Port forwarding tools: list, create, update, delete.

Uses V1 REST API per the endpoint catalog:
/proxy/network/api/s/{site}/rest/portforward
"""

from unifi_mcp.auth.client import UnifiClient


async def list_port_forwards(client: UnifiClient) -> list[dict]:
    """List all port forwarding rules."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/portforward",
        cache_category="port_forwarding", cache_ttl=30.0,
    )
    return [
        {
            "id": r.get("_id", ""),
            "name": r.get("name", ""),
            "fwd_ip": r.get("fwd_ip", ""),
            "fwd_port": r.get("fwd_port", ""),
            "dst_port": r.get("dst_port", ""),
            "proto": r.get("proto", ""),
            "enabled": r.get("enabled", True),
        }
        for r in response["data"]
    ]


async def create_port_forward(
    client: UnifiClient,
    name: str,
    fwd_ip: str,
    fwd_port: str,
    dst_port: str,
    proto: str = "tcp",
    enabled: bool = True,
    confirm: bool = False,
) -> dict:
    """Create a new port forwarding rule. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "fwd": fwd_ip,
        "fwd_port": fwd_port,
        "dst_port": dst_port,
        "proto": proto,
        "enabled": enabled,
    }

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
    """Update an existing port forwarding rule. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "update_port_forward",
            "rule_id": rule_id,
            "updates": updates,
            "message": f"Will update port forward {rule_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/portforward/{rule_id}",
        json=updates,
    )
    client.invalidate_cache("port_forwarding")
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
