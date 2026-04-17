"""QoS tools: list rules, get bandwidth profiles.

Uses V2 API per the endpoint catalog:
/proxy/network/v2/api/site/{site}/qos-rules
"""

from unifi_mcp.auth.client import UnifiClient


def _unwrap(response):
    """V2 endpoints may return a raw list or a {data: [...]} envelope."""
    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        return response.get("data", [])
    return []


async def list_qos_rules(client: UnifiClient) -> list[dict]:
    """List all QoS (Quality of Service) rules."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/qos-rules",
        cache_category="qos", cache_ttl=30.0,
    )
    return [
        {
            "id": r.get("_id", ""),
            "name": r.get("name", ""),
            "enabled": r.get("enabled", True),
            "action": r.get("action", ""),
            "rate_limit_up": r.get("rate_limit_up", 0),
            "rate_limit_down": r.get("rate_limit_down", 0),
        }
        for r in _unwrap(response)
    ]


async def get_bandwidth_profiles(client: UnifiClient) -> list[dict]:
    """Get bandwidth/QoS profiles (alias for listing QoS rules with profile details)."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/qos-rules",
        cache_category="qos", cache_ttl=30.0,
    )
    return _unwrap(response)


TOOLS = [list_qos_rules, get_bandwidth_profiles]
