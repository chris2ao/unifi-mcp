import importlib
from typing import Any


PRODUCT_MODULES: dict[str, list[str]] = {
    "network": [
        "system", "devices", "clients", "networks", "firewall", "zbf",
        "wifi", "vpn", "port_forwarding", "dpi", "hotspot", "mac_acl",
        "qos", "topology", "traffic_flows", "traffic_rules",
        "radius", "port_profiles", "backups", "webhooks",
    ],
    "protect": [
        "cameras", "events", "recordings", "devices",
    ],
    "access": [
        "doors", "credentials", "visitors", "policies",
    ],
}

# Probe endpoints to detect installed products
PRODUCT_PROBES: dict[str, str] = {
    "network": "/proxy/network/api/s/{site}/stat/sysinfo",
    "protect": "/proxy/protect/integration/v1/meta/info",
    "access": "/proxy/access/api/v2/bootstrap",
}


class ProductRegistry:
    """Tracks which product tool sets have been loaded."""

    def __init__(self) -> None:
        self._loaded: dict[str, int] = {}

    @property
    def products(self) -> dict[str, list[str]]:
        return PRODUCT_MODULES

    def is_loaded(self, product: str) -> bool:
        return product in self._loaded

    def mark_loaded(self, product: str, tool_count: int) -> None:
        self._loaded[product] = tool_count

    def get_summary(self) -> dict:
        return {
            product: {
                "loaded": product in self._loaded,
                "tool_count": self._loaded.get(product, 0),
            }
            for product in PRODUCT_MODULES
        }


def load_product_tools(product: str) -> list[Any]:
    """Import all tool modules for a product and collect their TOOLS lists."""
    if product not in PRODUCT_MODULES:
        raise ValueError(f"Unknown product: {product}")

    all_tools = []
    for module_name in PRODUCT_MODULES[product]:
        try:
            module = importlib.import_module(f"unifi_mcp.tools.{product}.{module_name}")
            tools = getattr(module, "TOOLS", [])
            all_tools.extend(tools)
        except ImportError:
            # Module not yet implemented, skip
            continue

    return all_tools
