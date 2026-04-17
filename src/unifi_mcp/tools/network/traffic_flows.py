"""Traffic flow analysis tools.

Per-flow data is not exposed by the API-key surface on Network 9.x / 10.x.
The Integration API does not include `traffic/flows`, and the legacy v1/v2
surfaces require cookie auth. Until the Integration API adds flow telemetry,
these tools return a structured `PRODUCT_UNAVAILABLE` error directing callers
to client-level traffic stats via `list_clients` (which exposes per-client
`tx_bytes` / `rx_bytes`).
"""

from unifi_mcp.auth.client import UnifiClient


_UNAVAILABLE = {
    "error": True,
    "category": "PRODUCT_UNAVAILABLE",
    "message": (
        "Per-flow traffic data is not exposed via the API-key Integration API "
        "on this Network firmware. Use list_clients for per-client tx_bytes / "
        "rx_bytes aggregates."
    ),
}


async def list_traffic_flows(client: UnifiClient, limit: int = 50) -> list[dict]:
    """List recent traffic flows. Currently unavailable via API key (see message)."""
    return [_UNAVAILABLE]


async def get_top_talkers(client: UnifiClient, limit: int = 10) -> list[dict]:
    """Get top traffic flows by bytes. Currently unavailable via API key (see message)."""
    return [_UNAVAILABLE]


async def filter_flows_by_app(client: UnifiClient, app_name: str) -> list[dict]:
    """Filter traffic flows by application name. Currently unavailable via API key."""
    return [_UNAVAILABLE]


async def filter_flows_by_client(client: UnifiClient, client_ip: str) -> list[dict]:
    """Filter traffic flows by source / destination IP. Currently unavailable via API key."""
    return [_UNAVAILABLE]


TOOLS = [list_traffic_flows, get_top_talkers, filter_flows_by_app, filter_flows_by_client]
