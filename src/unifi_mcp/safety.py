from datetime import datetime, timezone
from enum import StrEnum


class SafetyTier(StrEnum):
    EXECUTE = "execute"
    PREVIEW_CONFIRM = "preview_confirm"


# Tier 2 tools: tool_name -> cache_category
_TIER2_TOOLS: dict[str, str] = {
    # Network/VLAN mutations
    "create_network": "networks",
    "update_network": "networks",
    "delete_network": "networks",
    # Firewall mutations
    "create_firewall_rule": "firewall",
    "update_firewall_rule": "firewall",
    "delete_firewall_rule": "firewall",
    "reorder_firewall_rules": "firewall",
    "create_firewall_group": "firewall",
    "delete_firewall_group": "firewall",
    # ZBF mutations
    "create_zbf_policy": "zbf",
    "update_zbf_policy": "zbf",
    "delete_zbf_policy": "zbf",
    # Device mutations
    "restart_device": "devices",
    "upgrade_firmware": "devices",
    "forget_device": "devices",
    # Client mutations
    "block_client": "clients",
    "unblock_client": "clients",
    # WiFi mutations
    "create_wlan": "wifi",
    "update_wlan": "wifi",
    "delete_wlan": "wifi",
    # VPN mutations
    "create_vpn": "vpn",
    "update_vpn": "vpn",
    "delete_vpn": "vpn",
    # Port forwarding mutations
    "create_port_forward": "port_forwarding",
    "update_port_forward": "port_forwarding",
    "delete_port_forward": "port_forwarding",
    # RADIUS mutations
    "create_radius_profile": "radius",
    "update_radius_profile": "radius",
    "delete_radius_profile": "radius",
    # Port profile mutations
    "create_port_profile": "port_profiles",
    "update_port_profile": "port_profiles",
    "delete_port_profile": "port_profiles",
    # Backup mutations
    "restore_backup": "backups",
    # WiFi toggle (can disrupt wireless clients)
    "toggle_wlan": "wifi",
    # Device mutations (have confirm flow but were missing from tier dict)
    "adopt_device": "devices",
    "rf_scan": "devices",
    # MAC ACL mutations (can block device network access)
    "add_mac_filter": "mac_acl",
    "delete_mac_filter": "mac_acl",
}


class SafetyManager:
    """Manages safety tiers, preview-confirm flow, and mutation audit logging."""

    def __init__(self) -> None:
        self._previews: dict[str, dict] = {}
        self._mutation_log: list[dict] = []

    def get_tier(self, tool_name: str) -> SafetyTier:
        """Return the safety tier for a tool. Unknown tools default to EXECUTE."""
        if tool_name in _TIER2_TOOLS:
            return SafetyTier.PREVIEW_CONFIRM
        return SafetyTier.EXECUTE

    def get_category(self, tool_name: str) -> str | None:
        """Return the cache category for a Tier 2 tool, or None for Tier 1."""
        return _TIER2_TOOLS.get(tool_name)

    def record_preview(self, tool_name: str, params: dict) -> None:
        """Record that a preview was shown for a tool invocation."""
        self._previews[tool_name] = params

    def has_preview(self, tool_name: str) -> bool:
        """Check if a preview has been recorded for a tool."""
        return tool_name in self._previews

    def confirm_executed(self, tool_name: str) -> None:
        """Clear the preview record after confirmed execution."""
        self._previews.pop(tool_name, None)

    def log_mutation(self, tool_name: str, params: dict, result: dict) -> None:
        """Record a confirmed mutation to the audit log."""
        self._mutation_log.append({
            "tool": tool_name,
            "params": params,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_mutation_log(self) -> list[dict]:
        """Return the full mutation audit log."""
        return list(self._mutation_log)
