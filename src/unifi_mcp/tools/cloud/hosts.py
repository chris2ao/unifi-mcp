"""Site Manager inventory tools: hosts (consoles), sites, and devices across the account."""

from unifi_mcp.cloud.client import CloudClient
from unifi_mcp.tools.cloud._common import check_id, unwrap, validation_error

GROUP = "cloud"
TIER2_TOOLS: dict[str, str] = {}


async def list_cloud_hosts(client: CloudClient) -> list[dict]:
    """List all UniFi consoles and network servers (hosts) on the cloud account. Use first to find host IDs for other cloud tools."""
    return await client.get_paginated("/v1/hosts")


async def get_cloud_host(client: CloudClient, host_id: str) -> dict:
    """Get one cloud host (console) by host_id as returned by list_cloud_hosts, including reported state and owner info."""
    if (err := check_id(host_id, "host_id")):
        return err
    data = unwrap(await client.get(f"/v1/hosts/{host_id}"))
    if isinstance(data, list):
        data = next((h for h in data if isinstance(h, dict) and h.get("id") == host_id), None)
    if not isinstance(data, dict) or not data or data.get("id", host_id) != host_id:
        return {
            "error": True, "category": "NOT_FOUND",
            "message": f"No cloud host with id {host_id}. Use list_cloud_hosts to see valid ids.",
        }
    return data


async def list_cloud_sites(client: CloudClient) -> list[dict]:
    """List all sites across the cloud account with hostId, siteId, metadata, statistics (device and client counts) and permission."""
    return await client.get_paginated("/v1/sites")


async def list_cloud_devices(client: CloudClient, host_ids: list[str] | None = None) -> list[dict] | dict:
    """List UniFi devices grouped by host across the cloud account. Optionally limit to host_ids (list of host IDs from list_cloud_hosts)."""
    params: list[tuple[str, str]] = []
    if host_ids is not None:
        if not isinstance(host_ids, list) or not host_ids:
            return validation_error("host_ids must be a non-empty list of host ID strings, or omitted")
        for hid in host_ids:
            if (err := check_id(hid, "host_ids item")):
                return err
        params = [("hostIds[]", hid) for hid in host_ids]
    return await client.get_paginated("/v1/devices", params=params)
TOOLS = [list_cloud_hosts, get_cloud_host, list_cloud_sites, list_cloud_devices]
