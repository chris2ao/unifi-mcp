"""Network topology tools: graph, uplink tree, port table.

Uses stat/device endpoint to build topology from uplink fields, per the endpoint catalog.
"""

from unifi_mcp.auth.client import UnifiClient


async def get_topology(client: UnifiClient) -> dict:
    """Build a network topology graph from device uplink relationships.

    Returns a dict with 'nodes' (devices) and 'edges' (uplink connections).
    """
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/device",
        cache_category="devices", cache_ttl=30.0,
    )
    devices = response["data"]

    nodes = []
    edges = []
    for d in devices:
        nodes.append({
            "id": d.get("_id", ""),
            "mac": d.get("mac", ""),
            "name": d.get("name", d.get("mac", "")),
            "model": d.get("model", ""),
            "type": d.get("type", ""),
        })
        uplink = d.get("uplink", {})
        uplink_mac = uplink.get("uplink_mac", "")
        if uplink_mac:
            edges.append({
                "from_mac": uplink_mac,
                "to_mac": d.get("mac", ""),
                "type": uplink.get("type", "wire"),
                "speed": uplink.get("speed", 0),
            })

    return {"nodes": nodes, "edges": edges}


async def get_uplink_tree(client: UnifiClient) -> dict:
    """Build a hierarchical uplink tree with the gateway as root."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/device",
        cache_category="devices", cache_ttl=30.0,
    )
    devices = response["data"]

    # Index devices by MAC
    by_mac: dict[str, dict] = {}
    for d in devices:
        by_mac[d.get("mac", "")] = {
            "mac": d.get("mac", ""),
            "name": d.get("name", d.get("mac", "")),
            "type": d.get("type", ""),
            "model": d.get("model", ""),
            "children": [],
        }

    # Find root(s): devices with no uplink or uplink to unknown MAC
    roots = []
    for d in devices:
        uplink_mac = d.get("uplink", {}).get("uplink_mac", "")
        mac = d.get("mac", "")
        if not uplink_mac or uplink_mac not in by_mac:
            roots.append(by_mac[mac])
        else:
            by_mac[uplink_mac]["children"].append(by_mac[mac])

    # Return first root (typically the gateway), or empty if none
    if roots:
        return roots[0]
    return {"mac": "", "name": "unknown", "type": "", "model": "", "children": []}


async def get_port_table(client: UnifiClient, mac: str) -> list[dict]:
    """Get the port table for a specific device (switches, gateways)."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/device/{mac}",
        cache_category="devices", cache_ttl=15.0,
    )
    d = response["data"][0]
    return [
        {
            "port": p.get("port_idx"),
            "name": p.get("name", ""),
            "speed": p.get("speed", 0),
            "is_uplink": p.get("is_uplink", False),
        }
        for p in d.get("port_table", [])
    ]


TOOLS = [get_topology, get_uplink_tree, get_port_table]
