"""Routing insight tools: routing table, static routes, policy routes, NAT.

All tools are read-only (Tier 1). They use internal v2 and legacy endpoints
that work with the API key but have no public contract, so each tool fails
soft: on a 404, auth error, connection error, or unexpected response shape it
returns a structured error dict naming the endpoint instead of raising.

Endpoints:
- GET /proxy/network/v2/api/site/{site}/routes          (response {items, truncated})
- GET /proxy/network/api/s/{site}/rest/routing          (legacy static routes)
- GET /proxy/network/v2/api/site/{site}/trafficroutes   (policy-based routing)
- GET /proxy/network/v2/api/site/{site}/nat
"""

from collections.abc import Awaitable, Callable
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError

GROUP = "insights"
TIER2_TOOLS: dict[str, str] = {}

ROUTES_PATH = "/proxy/network/v2/api/site/{site}/routes"
STATIC_ROUTES_PATH = "/proxy/network/api/s/{site}/rest/routing"
TRAFFIC_ROUTES_PATH = "/proxy/network/v2/api/site/{site}/trafficroutes"
NAT_PATH = "/proxy/network/v2/api/site/{site}/nat"


def unexpected_shape(endpoint: str, detail: str) -> dict:
    """Build the structured error returned when a response shape is unusable."""
    return {
        "error": True,
        "category": str(ErrorCategory.UNEXPECTED_RESPONSE),
        "message": f"Unexpected response shape from {endpoint}: {detail}",
        "endpoint": endpoint,
    }


async def fail_soft(endpoint: str, fn: Callable[[], Awaitable[Any]]) -> Any:
    """Run a tool body; convert API errors and shape surprises to error dicts."""
    try:
        return await fn()
    except UnifiError as e:
        result = e.to_dict()
        result.setdefault("endpoint", endpoint)
        return result
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as e:
        return unexpected_shape(endpoint, f"{type(e).__name__}: {e}")


def extract_items(response: Any, *keys: str) -> list[dict]:
    """Pull a list of dict records from a bare list, {data: [...]}, or named key.

    Returns [] for an empty or null payload. Raises TypeError on a shape that
    holds no list at all (caught by fail_soft).
    """
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        found = [k for k in (*keys, "data") if k in response]
        if not found:
            raise TypeError(f"no list under {list(keys) + ['data']}")
        items = response[found[0]]
    elif response is None:
        return []
    else:
        raise TypeError(f"expected list or object, got {type(response).__name__}")
    if items is None:
        return []
    if not isinstance(items, list):
        raise TypeError(f"expected list, got {type(items).__name__}")
    return [i for i in items if isinstance(i, dict)]


def _format_nexthop(h: dict) -> dict:
    return {
        "interface": h.get("interface", ""),
        "gateway": h.get("via") or h.get("gateway", ""),
        "weight": h.get("weight"),
        "in_use": h.get("in_use"),
    }


def _format_route(r: dict) -> dict:
    hops = r.get("nexthops") or []
    return {
        "destination": r.get("destination", ""),
        "type": r.get("type", ""),
        "origin": r.get("origin", ""),
        "scope": r.get("scope"),
        "nexthops": [_format_nexthop(h) for h in hops if isinstance(h, dict)],
    }


async def get_routing_table(client: UnifiClient) -> dict:
    """Get the gateway's live routing table (kernel routes with next hops).

    Use to see which interface or gateway carries each destination network.
    Returns {routes, count, truncated}; truncated is True when the console cut
    the list short. Internal endpoint, may change between firmware versions.
    """
    async def run() -> dict:
        response = await client.get(ROUTES_PATH, cache_category="routing", cache_ttl=15.0)
        routes = [_format_route(r) for r in extract_items(response, "items")]
        truncated = bool(response.get("truncated", False)) if isinstance(response, dict) else False
        return {"routes": routes, "count": len(routes), "truncated": truncated}

    return await fail_soft(ROUTES_PATH, run)


def _format_static_route(r: dict) -> dict:
    return {
        "id": r.get("_id", ""),
        "name": r.get("name", ""),
        "enabled": r.get("enabled", True),
        "network": r.get("static-route_network", ""),
        "next_hop": r.get("static-route_nexthop", ""),
        "interface": r.get("static-route_interface", ""),
        "distance": r.get("static-route_distance"),
        "type": r.get("type", ""),
        "route_type": r.get("static-route_type", ""),
    }


async def list_static_routes(client: UnifiClient) -> list[dict] | dict:
    """List user-defined static routes (destination network, next hop, distance).

    Use to audit manually configured routes. Returns an empty list when none
    exist. Legacy endpoint; returns an error dict if the console rejects it.
    """
    async def run() -> list[dict]:
        response = await client.get(
            STATIC_ROUTES_PATH, cache_category="routing", cache_ttl=30.0
        )
        return [_format_static_route(r) for r in extract_items(response)]

    return await fail_soft(STATIC_ROUTES_PATH, run)


def _format_traffic_route(r: dict) -> dict:
    return {
        "id": r.get("_id") or r.get("id", ""),
        "description": r.get("description") or r.get("name", ""),
        "enabled": r.get("enabled", True),
        "matching_target": r.get("matching_target", ""),
        "network_id": r.get("network_id", ""),
        "target_devices": r.get("target_devices", []),
        "domains": r.get("domains", []),
        "ip_addresses": r.get("ip_addresses", []),
        "ip_ranges": r.get("ip_ranges", []),
        "regions": r.get("regions", []),
        "kill_switch_enabled": r.get("kill_switch_enabled"),
        "next_hop": r.get("next_hop", ""),
    }


async def list_traffic_routes(client: UnifiClient) -> list[dict] | dict:
    """List policy-based (traffic) routes that steer matching traffic to a WAN or VPN.

    Use to see which clients, domains, or IP ranges are routed over a specific
    uplink or VPN tunnel. Returns an empty list when none are configured.
    Internal v2 endpoint; returns an error dict if unavailable.
    """
    async def run() -> list[dict]:
        response = await client.get(
            TRAFFIC_ROUTES_PATH, cache_category="routing", cache_ttl=30.0
        )
        return [_format_traffic_route(r) for r in extract_items(response)]

    return await fail_soft(TRAFFIC_ROUTES_PATH, run)


def _format_nat_rule(r: dict) -> dict:
    return {
        "id": r.get("_id") or r.get("id", ""),
        "description": r.get("description") or r.get("name", ""),
        "enabled": r.get("enabled", True),
        "type": r.get("type", ""),
        "protocol": r.get("protocol", ""),
        "ip_address": r.get("ip_address", ""),
        "port": r.get("port", ""),
        "in_interface": r.get("in_interface", ""),
        "out_interface": r.get("out_interface", ""),
        "source_filter": r.get("source_filter", {}),
        "destination_filter": r.get("destination_filter", {}),
        "ip_version": r.get("ip_version", ""),
    }


async def list_nat_rules(client: UnifiClient) -> list[dict] | dict:
    """List NAT rules (masquerade, source NAT, destination NAT) configured on the gateway.

    Use to audit address translation beyond simple port forwards (see
    list_port_forwards for those). Returns an empty list when none exist.
    Internal v2 endpoint; returns an error dict if unavailable.
    """
    async def run() -> list[dict]:
        response = await client.get(NAT_PATH, cache_category="routing", cache_ttl=30.0)
        return [_format_nat_rule(r) for r in extract_items(response)]

    return await fail_soft(NAT_PATH, run)


TOOLS = [
    get_routing_table,
    list_static_routes,
    list_traffic_routes,
    list_nat_rules,
]
