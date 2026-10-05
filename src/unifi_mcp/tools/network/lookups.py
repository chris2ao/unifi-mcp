"""Lookup tools for the official Network Integration API (all read-only, Tier 1).

Covers the reference data other tools need to build requests: WANs, VPN
servers and site-to-site tunnels, device tags, DPI applications and
categories, countries, RADIUS profiles, and switching (stacks, LAGs, MC-LAG).

Every list uses the client's pagination helper so results are complete, not
just the first page of 25. Base: /proxy/network/integration/v1.
"""

from collections.abc import Callable
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import check_id, check_range, validation_error

GROUP = "core"
TIER2_TOOLS: dict[str, str] = {}

_BASE = "/proxy/network/integration/v1/sites/{site_id}"
_CATEGORY = "lookups"
_TTL = 60.0
# DPI and country catalogs are static per firmware, so cache them for an hour.
_STATIC_TTL = 3600.0


def _origin(item: dict) -> str:
    meta = item.get("metadata")
    return meta.get("origin", "") if isinstance(meta, dict) else ""


def _list_of(value: Any) -> list:
    return list(value) if isinstance(value, list) else []


async def _list(
    client: UnifiClient, path: str, fmt: Callable[[dict], dict], ttl: float = _TTL
) -> list[dict]:
    items = await client.get_all_pages(path, cache_category=_CATEGORY, cache_ttl=ttl)
    return [fmt(i) for i in items if isinstance(i, dict)]


async def _get_one(
    client: UnifiClient, path: str, fmt: Callable[[dict], dict]
) -> dict:
    try:
        response = await client.get(path, cache_category=_CATEGORY, cache_ttl=_TTL)
    except UnifiError as e:
        return e.to_dict()
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        data = response["data"]
        response = data[0] if data else {}
    if not isinstance(response, dict) or not response:
        return {
            "error": True,
            "category": str(ErrorCategory.NOT_FOUND),
            "message": f"Empty response from {path}",
        }
    return fmt(response)


def _fmt_named(i: dict) -> dict:
    return {"id": i.get("id", ""), "name": i.get("name", "")}


def _fmt_tunnel(i: dict) -> dict:
    return {**_fmt_named(i), "type": i.get("type", ""), "origin": _origin(i)}


def _fmt_tag(i: dict) -> dict:
    ids = _list_of(i.get("deviceIds"))
    return {**_fmt_named(i), "device_ids": ids, "device_count": len(ids), "origin": _origin(i)}


def _fmt_unit(u: dict) -> dict:
    return {
        "id": u.get("id"), "mac": u.get("macAddress", ""),
        "role": u.get("role", ""), "order": u.get("order"),
    }


def _fmt_stack(i: dict) -> dict:
    return {
        **_fmt_named(i),
        "device_id": i.get("deviceId", ""),
        "units": [_fmt_unit(u) for u in _list_of(i.get("units")) if isinstance(u, dict)],
        "lag_ids": [lag.get("id", "") for lag in _list_of(i.get("lags")) if isinstance(lag, dict)],
        "origin": _origin(i),
    }


def _fmt_lag(i: dict) -> dict:
    return {
        "id": i.get("id", ""),
        "type": i.get("type", ""),
        "members": _list_of(i.get("members")),
        "switch_stack_id": i.get("switchStackId"),
        "mc_lag_domain_id": i.get("mcLagDomainId"),
        "origin": _origin(i),
    }


def _fmt_peer(p: dict) -> dict:
    return {
        "role": p.get("role", ""), "device_id": p.get("deviceId", ""),
        "link_port_idxs": _list_of(p.get("linkPortIdxs")),
    }


def _fmt_domain(i: dict) -> dict:
    return {
        **_fmt_named(i),
        "peers": [_fmt_peer(p) for p in _list_of(i.get("peers")) if isinstance(p, dict)],
        "lags": [
            {"id": lag.get("id", ""), "members": _list_of(lag.get("members"))}
            for lag in _list_of(i.get("lags")) if isinstance(lag, dict)
        ],
        "origin": _origin(i),
    }


def _fmt_profile(i: dict) -> dict:
    return {**_fmt_named(i), "origin": _origin(i)}


def _fmt_vpn_server(i: dict) -> dict:
    return {
        **_fmt_named(i), "type": i.get("type", ""),
        "enabled": i.get("enabled"), "origin": _origin(i),
    }


async def list_wans(client: UnifiClient) -> list[dict]:
    """List the site's WAN interfaces (id and name). Use to get a WAN id for other tools."""
    return await _list(client, f"{_BASE}/wans", _fmt_named)


async def list_site_to_site_tunnels(client: UnifiClient) -> list[dict]:
    """List site-to-site VPN tunnels (id, name, type IPSEC/OPENVPN/WIREGUARD, origin)."""
    return await _list(client, f"{_BASE}/vpn/site-to-site-tunnels", _fmt_tunnel)


async def list_device_tags(client: UnifiClient) -> list[dict]:
    """List device tags with the ids of the devices carrying each tag (used by WiFi broadcast filters)."""
    return await _list(client, f"{_BASE}/device-tags", _fmt_tag)


async def search_dpi_applications(
    client: UnifiClient, query: str, limit: int = 25
) -> list[dict] | dict:
    """Search the DPI application catalog (about 2,100 apps) by name substring, case-insensitive.

    Use to find the integer application id for firewall or traffic rules.
    `query` is required (for example "zoom"); `limit` caps results (1 to 200,
    default 25). Names that start with the query are listed first.
    """
    if not isinstance(query, str) or not query.strip():
        return validation_error("query must be a non-empty string.")
    err = check_range(limit, 1, 200, "limit")
    if err:
        return err
    apps = await _list(client, "/proxy/network/integration/v1/dpi/applications", _fmt_named, _STATIC_TTL)
    needle = query.strip().lower()
    hits = [a for a in apps if needle in str(a["name"]).lower()]
    ranked = sorted(hits, key=lambda a: (not str(a["name"]).lower().startswith(needle), str(a["name"]).lower()))
    return ranked[: int(limit)]


async def list_dpi_categories(client: UnifiClient) -> list[dict]:
    """List DPI application categories (integer id and name)."""
    return await _list(client, "/proxy/network/integration/v1/dpi/categories", _fmt_named, _STATIC_TTL)


async def list_countries(client: UnifiClient, query: str | None = None) -> list[dict] | dict:
    """List countries (ISO 3166-1 alpha-2 code and name), optionally filtered.

    `query` matches the code or name by case-insensitive substring (for
    example "ger" or "DE"). Omit it to list all 248 countries.
    """
    if query is not None and not isinstance(query, str):
        return validation_error("query must be a string.")
    rows = await _list(
        client, "/proxy/network/integration/v1/countries",
        lambda i: {"code": i.get("code", ""), "name": i.get("name", "")}, _STATIC_TTL,
    )
    if not query or not query.strip():
        return rows
    needle = query.strip().lower()
    return [r for r in rows if needle in r["code"].lower() or needle in r["name"].lower()]


async def list_switch_stacks(client: UnifiClient) -> list[dict]:
    """List switch stacks (id, name, member units with roles, stack LAG ids)."""
    return await _list(client, f"{_BASE}/switching/switch-stacks", _fmt_stack)


async def get_switch_stack(client: UnifiClient, stack_id: str) -> dict:
    """Get one switch stack by id (units, roles, LAG ids)."""
    err = check_id(stack_id, "stack_id")
    if err:
        return err
    return await _get_one(client, f"{_BASE}/switching/switch-stacks/{stack_id}", _fmt_stack)


async def list_lags(client: UnifiClient) -> list[dict]:
    """List link aggregation groups (type LOCAL, SWITCH_STACK or MULTI_CHASSIS, with member ports)."""
    return await _list(client, f"{_BASE}/switching/lags", _fmt_lag)


async def get_lag(client: UnifiClient, lag_id: str) -> dict:
    """Get one link aggregation group by id (type and member ports)."""
    err = check_id(lag_id, "lag_id")
    if err:
        return err
    return await _get_one(client, f"{_BASE}/switching/lags/{lag_id}", _fmt_lag)


async def list_mc_lag_domains(client: UnifiClient) -> list[dict]:
    """List multi-chassis LAG domains (peers with TOP/BOTTOM roles and member LAGs)."""
    return await _list(client, f"{_BASE}/switching/mc-lag-domains", _fmt_domain)


async def get_mc_lag_domain(client: UnifiClient, domain_id: str) -> dict:
    """Get one multi-chassis LAG domain by id (peers and LAGs)."""
    err = check_id(domain_id, "domain_id")
    if err:
        return err
    return await _get_one(client, f"{_BASE}/switching/mc-lag-domains/{domain_id}", _fmt_domain)


async def list_radius_profiles_v1(client: UnifiClient) -> list[dict]:
    """List RADIUS profiles from the official API (id, name, origin only; no secrets)."""
    return await _list(client, f"{_BASE}/radius/profiles", _fmt_profile)


async def list_vpn_servers_v1(client: UnifiClient) -> list[dict]:
    """List VPN servers from the official API (id, name, type, enabled, origin)."""
    return await _list(client, f"{_BASE}/vpn/servers", _fmt_vpn_server)


TOOLS = [
    list_wans, list_site_to_site_tunnels, list_device_tags, search_dpi_applications,
    list_dpi_categories, list_countries, list_switch_stacks, get_switch_stack,
    list_lags, get_lag, list_mc_lag_domains, get_mc_lag_domain,
    list_radius_profiles_v1, list_vpn_servers_v1,
]
