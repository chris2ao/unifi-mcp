"""Optional Site Manager (cloud) tools. Loaded on demand by load_cloud_tools."""

from unifi_mcp.tools.cloud import hosts, isp_metrics, sdwan

GROUP = "cloud"
MODULES = (hosts, isp_metrics, sdwan)


def all_cloud_tools() -> list:
    """Collect TOOLS from every cloud module."""
    return [tool for module in MODULES for tool in module.TOOLS]
