"""Deep Packet Inspection (DPI) tools: site-level stats, per-client DPI.

Uses V1 stat API per the endpoint catalog.
"""

from unifi_mcp.auth.client import UnifiClient


async def get_dpi_stats(client: UnifiClient) -> list[dict]:
    """Get site-wide DPI statistics (application and category breakdown)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/dpi",
        cache_category="dpi", cache_ttl=30.0,
    )
    return response["data"]


async def get_dpi_by_app(client: UnifiClient, mac: str) -> list[dict]:
    """Get DPI traffic breakdown for a specific client by MAC address."""
    response = await client.post(
        "/proxy/network/api/s/{site}/stat/stadpi",
        json={"type": "by_app", "macs": [mac]},
    )
    return response["data"]


TOOLS = [get_dpi_stats, get_dpi_by_app]
