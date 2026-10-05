"""Custom firewall zone tools (create, update, delete) via the official Integration API.

Base path: /proxy/network/integration/v1/sites/{site_id}/firewall/zones (spec 10.6.106).
Zone ids are Integration UUIDs, as returned by list_zbf_zones. System-defined zones
(Internal, External, Gateway, Vpn, Hotspot, Dmz) cannot be deleted or renamed.
Network ids may be Integration UUIDs or the legacy 24-character ids returned by
list_networks; legacy ids are mapped to Integration UUIDs by network name.
"""

import re

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.tools.network.networks import _to_integration_id
from unifi_mcp.tools.network.zbf_official import (
    _BASE, _CACHE, _UUID_RE, _check_uuid, _executed, _first_error,
    _not_found, _preview, _unwrap,
)
from unifi_mcp.validation import validation_error

GROUP = "security"

_LEGACY_ID_RE = re.compile(r"^[0-9a-fA-F]{24}$")

TIER2_TOOLS = {
    "create_zbf_zone": "zbf",
    "update_zbf_zone": "zbf",
    "delete_zbf_zone": "zbf",
}


async def _fetch_zone(client: UnifiClient, zone_id: str) -> dict:
    return _unwrap(await client.get(f"{_BASE}/zones/{zone_id}"))


def _check_network_ids(value, field: str = "network_ids") -> dict | None:
    """Structural check: a list of network UUIDs or legacy list_networks ids."""
    if not isinstance(value, list):
        return validation_error(f"{field} must be a list of network ids.")
    for item in value:
        if not isinstance(item, str) or not (_UUID_RE.fullmatch(item) or _LEGACY_ID_RE.fullmatch(item)):
            return validation_error(
                f"{field} entries must be network ids: an Integration network UUID or the "
                f"'_id' returned by list_networks (policy ids do not belong here). Got: {item!r}."
            )
    return None


async def _resolve_network_ids(client: UnifiClient, ids: list[str]) -> tuple[list[str], dict | None]:
    """Map legacy network ids to Integration UUIDs. Returns (ids, error)."""
    resolved: list[str] = []
    for item in ids:
        uuid = await _to_integration_id(client, item)
        if not uuid:
            return [], validation_error(
                f"Network '{item}' has no matching Integration network UUID. "
                "Use get_network_references to look up a network's Integration id."
            )
        resolved.append(uuid)
    return resolved, None


def _check_zone_name(name) -> dict | None:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 128:
        return validation_error("name must be a non-empty string of at most 128 characters.")
    return None


async def create_zbf_zone(
    client: UnifiClient, name: str, network_ids: list[str], confirm: bool = False,
) -> dict:
    """Create a custom firewall zone with name and network_ids (network UUIDs or list_networks ids; may be empty). Requires confirm=True after previewing."""
    if err := _first_error(_check_zone_name(name), _check_network_ids(network_ids)):
        return err
    network_ids, err = await _resolve_network_ids(client, network_ids)
    if err:
        return err
    if not confirm:
        return _preview(
            "create_zbf_zone",
            f"Will create custom ZBF zone '{name}' with {len(network_ids)} network(s). "
            "Call again with confirm=True to execute.",
            name=name, network_ids=list(network_ids),
        )
    response = await client.post(
        f"{_BASE}/zones", json={"name": name, "networkIds": list(network_ids)},
    )
    client.invalidate_cache(_CACHE)
    return _executed("create_zbf_zone", response, name=name)


async def update_zbf_zone(
    client: UnifiClient,
    zone_id: str,
    name: str | None = None,
    network_ids: list[str] | None = None,
    confirm: bool = False,
) -> dict:
    """Rename a zone and/or replace its network_ids (GET-merge-PUT). Requires confirm=True after previewing.

    Omitted fields keep their current value. network_ids replaces the whole
    list. System-defined zones accept network changes only, not renames.
    """
    if err := _first_error(
        _check_uuid(zone_id, "zone_id"),
        _check_zone_name(name) if name is not None else None,
        _check_network_ids(network_ids) if network_ids is not None else None,
    ):
        return err
    if name is None and network_ids is None:
        return validation_error("Provide name and/or network_ids to update.")
    if network_ids is not None:
        network_ids, err = await _resolve_network_ids(client, network_ids)
        if err:
            return err
    current = await _fetch_zone(client, zone_id)
    if not current:
        return _not_found("zone", zone_id)
    if name is not None and name != current.get("name") and _is_system(current):
        return validation_error("System-defined zones cannot be renamed; only network_ids can change.")
    merged = {
        "name": current.get("name", "") if name is None else name,
        "networkIds": list(current.get("networkIds", []) if network_ids is None else network_ids),
    }
    if not confirm:
        return _preview(
            "update_zbf_zone",
            f"Will update ZBF zone '{current.get('name', zone_id)}'. "
            "Call again with confirm=True to execute.",
            zone_id=zone_id,
            current={"name": current.get("name", ""), "network_ids": current.get("networkIds", [])},
            updated={"name": merged["name"], "network_ids": merged["networkIds"]},
        )
    response = await client.put(f"{_BASE}/zones/{zone_id}", json=merged)
    client.invalidate_cache(_CACHE)
    return _executed("update_zbf_zone", response, zone_id=zone_id)


def _is_system(zone: dict) -> bool:
    return (zone.get("metadata") or {}).get("origin") == "SYSTEM_DEFINED"


async def delete_zbf_zone(client: UnifiClient, zone_id: str, confirm: bool = False) -> dict:
    """Delete a custom (user-defined) firewall zone by UUID. Requires confirm=True after previewing.

    System-defined zones (Internal, External, Gateway, Vpn, Hotspot, Dmz) cannot
    be deleted. Policies and networks that reference the zone may be affected.
    """
    if err := _check_uuid(zone_id, "zone_id"):
        return err
    current = await _fetch_zone(client, zone_id)
    if not current:
        return _not_found("zone", zone_id)
    if _is_system(current):
        return validation_error(
            f"Zone '{current.get('name', zone_id)}' is system-defined; only custom zones can be deleted."
        )
    if not confirm:
        return _preview(
            "delete_zbf_zone",
            f"Will delete custom ZBF zone '{current.get('name', zone_id)}'. "
            "Call again with confirm=True to execute.",
            impact="Policies that reference this zone may be removed or stop matching, and "
            "networks assigned to it lose their zone membership. This cannot be undone.",
            zone_id=zone_id, name=current.get("name", ""),
            network_ids=current.get("networkIds", []),
        )
    response = await client.delete(f"{_BASE}/zones/{zone_id}")
    client.invalidate_cache(_CACHE)
    return _executed("delete_zbf_zone", response, expect_body=False, zone_id=zone_id)


TOOLS = [create_zbf_zone, update_zbf_zone, delete_zbf_zone]
