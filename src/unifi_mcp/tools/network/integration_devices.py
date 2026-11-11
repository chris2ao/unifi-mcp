"""Network device tools on the Integration API (Tier 1, read-only).

Endpoints:
- GET /proxy/network/integration/v1/sites
- GET /proxy/network/integration/v1/sites/{site_id}/devices   (offset / limit)
- GET /proxy/network/integration/v1/sites/{site_id}/devices/{device_id}
- GET /proxy/network/integration/v1/sites/{site_id}/devices/{device_id}/statistics/latest

On some UniFi OS Server installs the legacy `/proxy/network/api/s/{site}/...`
device paths hang or are missing, while the Integration API answers. These
tools give device, radio and statistics reads that work there. They are their own
group, so a client can preload just them (UNIFI_PRELOAD_GROUPS=network:integration).
"""

import re
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError

GROUP = "integration"
TIER2_TOOLS: dict[str, str] = {}

SITES_PATH = "/proxy/network/integration/v1/sites"
DEVICES_PATH = "/proxy/network/integration/v1/sites/{site_id}/devices"
DEVICE_PATH = DEVICES_PATH + "/{device_id}"
STATS_PATH = DEVICE_PATH + "/statistics/latest"
PAGE_LIMIT = 100
MAX_PAGES = 50
_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def _items(response: Any) -> list[dict]:
    raw = response.get("data", []) if isinstance(response, dict) else response
    return [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _radios(payload: dict) -> list:
    radios = _dict(payload.get("interfaces")).get("radios")
    return radios if isinstance(radios, list) else []


def _summary(d: dict) -> dict:
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "model": d.get("model"),
        "mac": d.get("macAddress"),
        "ip": d.get("ipAddress"),
        "state": d.get("state"),
        "firmware": d.get("firmwareVersion"),
        "features": d.get("features") or [],
        "interfaces": d.get("interfaces") or [],
    }


def _is_ap(device: dict) -> bool:
    features = device.get("features") or []
    interfaces = device.get("interfaces") or []
    if "accessPoint" in features:  # list of names, or a dict keyed by feature
        return True
    return "radios" in interfaces


def _validation(message: str, endpoint: str) -> UnifiError:
    return UnifiError(ErrorCategory.VALIDATION_ERROR, message, endpoint=endpoint)


async def integration_list_sites(client: UnifiClient) -> list[dict]:
    """List Network sites on the Integration API (id, internalReference, name)."""
    response = await client.get(SITES_PATH, cache_category="integration_sites", cache_ttl=60.0)
    return [
        {"id": s.get("id"), "internal_reference": s.get("internalReference"), "name": s.get("name")}
        for s in _items(response)
    ]


async def integration_list_devices(client: UnifiClient) -> list[dict]:
    """List adopted devices (APs, switches, gateways) on the Integration API.

    Summary only; use integration_get_device for radio channel and width.
    """
    items: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        page = await client.get(
            f"{DEVICES_PATH}?offset={offset}&limit={PAGE_LIMIT}",
            cache_category="integration_devices",
            cache_ttl=15.0,
        )
        data = _items(page)
        items.extend(data)
        offset += len(data)
        total = page.get("totalCount") if isinstance(page, dict) else None
        if not data or not isinstance(total, int) or offset >= total:
            break
    return [_summary(d) for d in items]


async def _resolve_device_id(client: UnifiClient, device_id: str | None, mac: str | None, endpoint: str) -> str:
    if device_id:
        return device_id
    if not mac:
        raise _validation("Provide device_id (Integration API UUID) or mac", endpoint)
    wanted = mac.strip().lower().replace("-", ":")
    if not _MAC_RE.match(wanted):
        raise _validation(f"mac must look like aa:bb:cc:dd:ee:ff, got {mac[:40]!r}", endpoint)
    for device in await integration_list_devices(client):
        if (device.get("mac") or "").lower() == wanted and device.get("id"):
            return device["id"]
    raise UnifiError(ErrorCategory.NOT_FOUND, f"No device with mac {wanted}", endpoint=endpoint)


async def integration_get_device(client: UnifiClient, device_id: str | None = None, mac: str | None = None) -> dict:
    """Device detail on the Integration API, including per-radio channel and width.

    Give the Integration API device id (UUID) or its MAC address. Radios carry
    frequencyGHz, channel, channelWidthMHz and wlanStandard. The Integration API
    does not report TX power.
    """
    device_id = await _resolve_device_id(client, device_id, mac, "integration_get_device")
    detail = _dict(await client.get(
        DEVICE_PATH.replace("{device_id}", device_id),
        cache_category="integration_device",
        cache_ttl=15.0,
    ))
    return {
        "id": detail.get("id"),
        "name": detail.get("name"),
        "model": detail.get("model"),
        "mac": detail.get("macAddress"),
        "ip": detail.get("ipAddress"),
        "state": detail.get("state"),
        "firmware": detail.get("firmwareVersion"),
        "adopted_at": detail.get("adoptedAt"),
        "provisioned_at": detail.get("provisionedAt"),
        "radios": _radios(detail),
        "raw_interfaces": detail.get("interfaces"),
        "note": "TX power is not exposed by the UniFi Network Integration API",
    }


async def integration_get_device_stats(
    client: UnifiClient, device_id: str | None = None, mac: str | None = None,
) -> dict:
    """Latest device statistics on the Integration API: uptime, CPU, memory, uplink, per-radio TX retries."""
    device_id = await _resolve_device_id(client, device_id, mac, "integration_get_device_stats")
    stats = _dict(await client.get(
        STATS_PATH.replace("{device_id}", device_id),
        cache_category="integration_stats",
        cache_ttl=10.0,
    ))
    return {
        "device_id": device_id,
        "uptime_sec": stats.get("uptimeSec"),
        "cpu_pct": stats.get("cpuUtilizationPct"),
        "memory_pct": stats.get("memoryUtilizationPct"),
        "load_1m": stats.get("loadAverage1Min"),
        "uplink": stats.get("uplink"),
        "radios": _radios(stats),
        "last_heartbeat_at": stats.get("lastHeartbeatAt"),
    }


async def integration_get_ap_radios(client: UnifiClient) -> list[dict]:
    """Every access point with radio channel/width and live TX retry %, in one call (Wi-Fi triage)."""
    results = []
    for device in await integration_list_devices(client):
        if not _is_ap(device) or not device.get("id"):
            continue
        try:
            detail = await integration_get_device(client, device_id=device["id"])
            stats = await integration_get_device_stats(client, device_id=device["id"])
        except UnifiError as err:
            results.append({"name": device.get("name"), "error": err.message})
            continue
        results.append({
            "name": detail.get("name"),
            "mac": detail.get("mac"),
            "ip": detail.get("ip"),
            "model": detail.get("model"),
            "state": detail.get("state"),
            "firmware": detail.get("firmware"),
            "radios_config": detail.get("radios"),
            "cpu_pct": stats.get("cpu_pct"),
            "memory_pct": stats.get("memory_pct"),
            "radios_stats": stats.get("radios"),
            "uplink": stats.get("uplink"),
        })
    return results


TOOLS = [
    integration_list_sites,
    integration_list_devices,
    integration_get_device,
    integration_get_device_stats,
    integration_get_ap_radios,
]
