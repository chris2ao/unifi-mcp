"""Site Manager SD-WAN tools (read-only)."""

from unifi_mcp.cloud.client import CloudClient
from unifi_mcp.tools.cloud._common import as_list, check_id, unwrap

GROUP = "cloud"
TIER2_TOOLS: dict[str, str] = {}


async def list_sdwan_configs(client: CloudClient) -> list[dict]:
    """List SD-WAN configurations (id, name, type) on the cloud account."""
    return as_list(await client.get("/v1/sd-wan-configs"))


async def get_sdwan_config(client: CloudClient, config_id: str) -> dict:
    """Get one SD-WAN configuration by config_id from list_sdwan_configs, including hubs, spokes and connections."""
    if (err := check_id(config_id, "config_id")):
        return err
    data = unwrap(await client.get(f"/v1/sd-wan-configs/{config_id}"))
    return data if isinstance(data, dict) else {}


async def get_sdwan_status(client: CloudClient, config_id: str) -> dict:
    """Get live deployment status of an SD-WAN configuration (hub and spoke WAN status, latency, fingerprint, last update) by config_id."""
    if (err := check_id(config_id, "config_id")):
        return err
    data = unwrap(await client.get(f"/v1/sd-wan-configs/{config_id}/status"))
    return data if isinstance(data, dict) else {}


TOOLS = [list_sdwan_configs, get_sdwan_config, get_sdwan_status]
