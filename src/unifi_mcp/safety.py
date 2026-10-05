"""Safety tiers, enforced preview-confirm bookkeeping, and the mutation audit log.

Tier 2 tools (anything with a `confirm` parameter) must be previewed with
confirm=False before the server lets a confirm=True call through. The server
wrapper in `unifi_mcp.server` hashes the call parameters and uses
`record_preview` / `consume_preview` here to enforce that.

Tier classification (`get_tier` / `get_category`) reads a merged map: the
legacy per-module declarations below, plus the module-level TIER2_TOOLS of
every tool module, applied with `apply_tool_tiers` when modules are loaded.
The `confirm` parameter stays the enforcement mechanism; the merged map is
what reports and docs use, and tests keep the two in sync.
"""

import copy
import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class SafetyTier(StrEnum):
    EXECUTE = "execute"
    PREVIEW_CONFIRM = "preview_confirm"


# Legacy Tier 2 declarations for modules written before v0.6.0, keyed by
# "<product>.<module>" and mapping tool_name -> cache_category. From v0.6.0 each
# tool module declares its own module-level TIER2_TOOLS; the registry merges
# both (see unifi_mcp.tools._registry.module_tier2_tools). A legacy entry only
# applies to a tool that is still exported by the module it is listed under, so
# a tool that moves to another module takes that module's declaration.
_LEGACY_TIER2_BY_MODULE: dict[str, dict[str, str]] = {
    # Network/VLAN mutations
    "network.networks": {
        "create_network": "networks",
        "update_network": "networks",
        "delete_network": "networks",
    },
    # Firewall mutations
    "network.firewall": {
        "create_firewall_rule": "firewall",
        "update_firewall_rule": "firewall",
        "delete_firewall_rule": "firewall",
        "reorder_firewall_rules": "firewall",
        "create_firewall_group": "firewall",
        "delete_firewall_group": "firewall",
    },
    # ZBF mutations
    "network.zbf": {
        "create_zbf_policy": "zbf",
        "update_zbf_policy": "zbf",
        "delete_zbf_policy": "zbf",
    },
    # Device mutations
    "network.devices": {
        "restart_device": "devices",
        "upgrade_firmware": "devices",
        "forget_device": "devices",
        "adopt_device": "devices",
        "rf_scan": "devices",
    },
    # Client mutations
    "network.clients": {
        "block_client": "clients",
        "unblock_client": "clients",
    },
    # WiFi mutations (toggle can disrupt wireless clients)
    "network.wifi": {
        "create_wlan": "wifi",
        "update_wlan": "wifi",
        "delete_wlan": "wifi",
        "toggle_wlan": "wifi",
    },
    # Port forwarding mutations
    "network.port_forwarding": {
        "create_port_forward": "port_forwarding",
        "update_port_forward": "port_forwarding",
        "delete_port_forward": "port_forwarding",
    },
    # Traffic rule mutations
    "network.traffic_rules": {
        "create_traffic_rule": "traffic_rules",
        "update_traffic_rule": "traffic_rules",
        "delete_traffic_rule": "traffic_rules",
        "toggle_traffic_rule": "traffic_rules",
    },
    # RADIUS mutations
    "network.radius": {
        "create_radius_profile": "radius",
        "update_radius_profile": "radius",
        "delete_radius_profile": "radius",
    },
    # Port profile mutations
    "network.port_profiles": {
        "create_port_profile": "port_profiles",
        "update_port_profile": "port_profiles",
        "delete_port_profile": "port_profiles",
    },
    # Backup mutations
    "network.backups": {
        "restore_backup": "backups",
    },
    # MAC ACL mutations (can block device network access)
    "network.mac_acl": {
        "add_mac_filter": "mac_acl",
        "delete_mac_filter": "mac_acl",
    },
    # Protect camera actions (stubs or real, they take confirm)
    "protect.cameras": {
        "set_camera_recording_mode": "protect_cameras",
    },
    "protect.devices": {
        "reboot_camera": "protect_cameras",
    },
}

# Flat view of the legacy map (tool_name -> cache_category). A SafetyManager
# starts from this so it classifies legacy tools before any module is merged.
_TIER2_TOOLS: dict[str, str] = {
    name: category
    for mapping in _LEGACY_TIER2_BY_MODULE.values()
    for name, category in mapping.items()
}


def legacy_tier2_for(module_key: str) -> dict[str, str]:
    """Return a copy of the legacy Tier 2 entries for "<product>.<module>" (empty if none)."""
    return dict(_LEGACY_TIER2_BY_MODULE.get(module_key, {}))


_SECRET_KEY_PARTS = ("pass", "secret", "key", "token", "psk")
_MASK = "***"
DEFAULT_PREVIEW_TTL_SECONDS = 600
DEFAULT_MAX_PREVIEWS = 256
DEFAULT_MAX_LOG_ENTRIES = 500


def _normalize_numbers(value: Any) -> Any:
    """Treat integral floats as ints so 1 and 1.0 hash the same."""
    if isinstance(value, dict):
        return {k: _normalize_numbers(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_numbers(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def params_hash(params: dict) -> str:
    """Canonical SHA-256 of call parameters (sorted keys, non-JSON values via str)."""
    canonical = json.dumps(_normalize_numbers(params), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return lowered.startswith("x_") or any(part in lowered for part in _SECRET_KEY_PARTS)


def mask_secrets(value: Any) -> Any:
    """Return a copy of value with secret-looking dict entries replaced by '***'."""
    if isinstance(value, dict):
        return {
            k: (_MASK if _is_secret_key(k) else mask_secrets(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [mask_secrets(v) for v in value]
    return value


class SafetyManager:
    """Manages safety tiers, preview-confirm enforcement, and mutation audit logging."""

    def __init__(
        self,
        preview_ttl_seconds: float = DEFAULT_PREVIEW_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        max_previews: int = DEFAULT_MAX_PREVIEWS,
        max_log_entries: int = DEFAULT_MAX_LOG_ENTRIES,
    ) -> None:
        if preview_ttl_seconds <= 0:
            raise ValueError("preview_ttl_seconds must be positive")
        if max_previews < 1 or max_log_entries < 1:
            raise ValueError("max_previews and max_log_entries must be at least 1")
        self.preview_ttl_seconds = preview_ttl_seconds
        self._clock = clock
        self._max_previews = max_previews
        self._max_log_entries = max_log_entries
        # (tool_name, params_hash) -> monotonic time the preview was shown
        self._previews: dict[tuple[str, str], float] = {}
        self._mutation_log: list[dict] = []
        # Merged Tier 2 map: the legacy declarations, then module TIER2_TOOLS
        # applied through apply_tool_tiers as tool modules are loaded.
        self._tier2: dict[str, str] = dict(_TIER2_TOOLS)

    def get_tier(self, tool_name: str) -> SafetyTier:
        """Return the safety tier for a tool. Unknown tools default to EXECUTE."""
        if tool_name in self._tier2:
            return SafetyTier.PREVIEW_CONFIRM
        return SafetyTier.EXECUTE

    def get_category(self, tool_name: str) -> str | None:
        """Return the cache category for a Tier 2 tool, or None for Tier 1."""
        return self._tier2.get(tool_name)

    @property
    def tier2_tools(self) -> dict[str, str]:
        """A copy of the merged Tier 2 map (tool_name -> cache_category)."""
        return dict(self._tier2)

    def apply_tool_tiers(self, tool_names: Iterable[str], tier2: Mapping[str, str]) -> None:
        """Make `tier2` authoritative for one module's tools.

        Every name in `tier2` becomes Tier 2 with its cache category. Every
        other name in `tool_names` becomes Tier 1, which drops a stale legacy
        entry for a tool that a module now declares as Tier 1. Tools outside
        `tool_names` and `tier2` keep their current tier.
        """
        if not isinstance(tier2, Mapping):
            raise TypeError("tier2 must be a mapping of tool_name -> cache_category")
        bad = [name for name, cat in tier2.items() if not isinstance(name, str)
               or not isinstance(cat, str) or not name or not cat]
        if bad:
            raise ValueError(f"Invalid Tier 2 entries (need non-empty str -> str): {bad!r}")
        covered = set(tool_names) | set(tier2)
        kept = {name: cat for name, cat in self._tier2.items() if name not in covered}
        self._tier2 = {**kept, **tier2}

    # --- preview bookkeeping ---

    def _is_fresh(self, recorded_at: float) -> bool:
        return self._clock() - recorded_at <= self.preview_ttl_seconds

    def _prune(self) -> None:
        live = {k: t for k, t in self._previews.items() if self._is_fresh(t)}
        if len(live) > self._max_previews:
            newest = sorted(live.items(), key=lambda item: item[1])[-self._max_previews:]
            live = dict(newest)
        self._previews = live

    def record_preview(self, tool_name: str, params: dict) -> None:
        """Record that a preview was shown for this tool with these exact params."""
        key = (tool_name, params_hash(params))
        self._previews = {
            **{k: t for k, t in self._previews.items() if k != key},
            key: self._clock(),
        }
        self._prune()

    def consume_preview(self, tool_name: str, params: dict) -> bool:
        """Return True and discard the record if a fresh matching preview exists.

        Single use: a second call with the same params returns False. Expired
        records are discarded and return False.
        """
        key = (tool_name, params_hash(params))
        recorded_at = self._previews.get(key)
        if recorded_at is None:
            return False
        self._previews = {k: t for k, t in self._previews.items() if k != key}
        return self._is_fresh(recorded_at)

    def has_preview(self, tool_name: str, params: dict | None = None) -> bool:
        """Check for a fresh preview for a tool (any params, or the exact params given)."""
        if params is not None:
            recorded_at = self._previews.get((tool_name, params_hash(params)))
            return recorded_at is not None and self._is_fresh(recorded_at)
        return any(
            name == tool_name and self._is_fresh(t)
            for (name, _), t in self._previews.items()
        )

    def confirm_executed(self, tool_name: str, params: dict | None = None) -> None:
        """Clear preview records for a tool (all of them, or only the given params)."""
        if params is None:
            self._previews = {k: t for k, t in self._previews.items() if k[0] != tool_name}
            return
        key = (tool_name, params_hash(params))
        self._previews = {k: t for k, t in self._previews.items() if k != key}

    # --- audit log ---

    def log_mutation(self, tool_name: str, params: dict, result: Any) -> None:
        """Record a confirmed mutation. Secret-looking params are masked at write time."""
        entry = {
            "tool": tool_name,
            "params": mask_secrets(params),
            "result": mask_secrets(result),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._mutation_log = [*self._mutation_log, entry][-self._max_log_entries:]

    def get_mutation_log(self) -> list[dict]:
        """Return a deep copy of the audit log with secret-looking params masked."""
        return [
            {**copy.deepcopy(entry), "params": mask_secrets(entry["params"])}
            for entry in self._mutation_log
        ]
