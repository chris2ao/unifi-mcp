"""Device operations via the official Network Integration API.

Resolves devices by Integration id or MAC address and exposes latest
statistics, adopted-device details, pending adoption candidates, and PoE port
power cycling. Base path: /proxy/network/integration/v1.
"""

from __future__ import annotations

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import check_id, check_mac, normalize_mac, validation_error

GROUP = "core"

TIER2_TOOLS: dict[str, str] = {"power_cycle_port": "devices"}

_BASE = "/proxy/network/integration/v1"
_DEVICES = _BASE + "/sites/{site_id}/devices"


def _not_found(device: str) -> dict:
    return {
        "error": True,
        "category": "NOT_FOUND",
        "message": f"No adopted device found for '{device}'",
        "device": device,
    }


def _unwrap(response) -> dict | None:
    """Return a single object from {"data": [...]}, {"data": {...}}, a list or a bare dict."""
    if isinstance(response, list):
        return response[0] if response and isinstance(response[0], dict) else None
    if isinstance(response, dict):
        if "data" in response:
            data = response["data"]
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        return response or None
    return None


async def _resolve_device_id(client: UnifiClient, device: str) -> tuple[str | None, dict | None]:
    """Map an Integration id or MAC address to an Integration device id.

    Returns (device_id, None) on success or (None, error_dict).
    """
    if not isinstance(device, str) or not device:
        return None, validation_error("device must be an Integration device id or a MAC address.")
    if check_mac(device) is None:
        mac = normalize_mac(device)
        items = await client.get_all_pages(_DEVICES, filter=f"macAddress.eq('{mac}')")
        for item in items:
            if isinstance(item, dict) and str(item.get("macAddress", "")).lower() == mac:
                return item.get("id"), None
        return None, _not_found(device)
    err = check_id(device, "device")
    if err:
        return None, err
    return device, None


async def _fetch_details(client: UnifiClient, device_id: str) -> dict | None:
    """GET one adopted device, or None when it does not exist."""
    try:
        response = await client.get(f"{_DEVICES}/{device_id}")
    except UnifiError as e:
        if e.category == ErrorCategory.NOT_FOUND:
            return None
        raise
    return _unwrap(response)


def _format_uptime(seconds) -> str:
    if not isinstance(seconds, int) or seconds < 0:
        return ""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    return f"{days}d {hours}h {rem // 60}m"


def _format_statistics(device_id: str, s: dict) -> dict:
    uplink = s.get("uplink") or {}
    interfaces = s.get("interfaces") or {}
    radios = [
        {"frequency_ghz": r.get("frequencyGHz"), "tx_retries_pct": r.get("txRetriesPct")}
        for r in interfaces.get("radios", []) or []
    ]
    return {
        "device_id": device_id,
        "uptime_sec": s.get("uptimeSec"),
        "uptime": _format_uptime(s.get("uptimeSec")),
        "cpu_pct": s.get("cpuUtilizationPct"),
        "memory_pct": s.get("memoryUtilizationPct"),
        "load_average": {
            "1m": s.get("loadAverage1Min"),
            "5m": s.get("loadAverage5Min"),
            "15m": s.get("loadAverage15Min"),
        },
        "uplink": {"tx_bps": uplink.get("txRateBps"), "rx_bps": uplink.get("rxRateBps")},
        "radios": radios,
        "last_heartbeat_at": s.get("lastHeartbeatAt"),
        "next_heartbeat_at": s.get("nextHeartbeatAt"),
    }


def _format_port(p: dict) -> dict:
    out = {
        "idx": p.get("idx"),
        "state": p.get("state"),
        "connector": p.get("connector"),
        "speed_mbps": p.get("speedMbps"),
        "max_speed_mbps": p.get("maxSpeedMbps"),
    }
    poe = p.get("poe")
    if isinstance(poe, dict):
        out["poe"] = {
            "standard": poe.get("standard"),
            "enabled": poe.get("enabled"),
            "state": poe.get("state"),
        }
    return out


def _format_device(d: dict) -> dict:
    features = d.get("features") or {}
    interfaces = d.get("interfaces") or {}
    lags = (features.get("switching") or {}).get("lags", []) if isinstance(
        features.get("switching"), dict) else []
    return {
        "id": d.get("id", ""),
        "mac": d.get("macAddress", ""),
        "ip": d.get("ipAddress", ""),
        "name": d.get("name", ""),
        "model": d.get("model", ""),
        "state": d.get("state", ""),
        "supported": d.get("supported"),
        "firmware": {
            "version": d.get("firmwareVersion", ""),
            "updatable": d.get("firmwareUpdatable"),
        },
        "provisioning": {
            "adopted_at": d.get("adoptedAt"),
            "provisioned_at": d.get("provisionedAt"),
            "configuration_id": d.get("configurationId"),
        },
        "uplink_device_id": (d.get("uplink") or {}).get("deviceId"),
        "features": sorted(features.keys()),
        "lags": lags,
        "ports": [_format_port(p) for p in interfaces.get("ports", []) or []],
        "radios": [
            {
                "wlan_standard": r.get("wlanStandard"),
                "frequency_ghz": r.get("frequencyGHz"),
                "channel": r.get("channel"),
                "channel_width_mhz": r.get("channelWidthMHz"),
            }
            for r in interfaces.get("radios", []) or []
        ],
    }


async def get_device_statistics(client: UnifiClient, device: str) -> dict:
    """Get latest live statistics for one adopted device (Integration API).

    Use for health checks: uptime, CPU %, memory %, load averages, uplink
    tx/rx rate (bits per second) and per-radio retry %. `device` is the
    Integration device id or the MAC address.
    """
    device_id, err = await _resolve_device_id(client, device)
    if err:
        return err
    try:
        response = await client.get(f"{_DEVICES}/{device_id}/statistics/latest")
    except UnifiError as e:
        if e.category == ErrorCategory.NOT_FOUND:
            return _not_found(device)
        raise
    stats = _unwrap(response)
    if stats is None:
        return _not_found(device)
    return _format_statistics(device_id, stats)


async def get_device_details_v1(client: UnifiClient, device: str) -> dict:
    """Get Integration API details for one adopted device.

    Returns features (switching, accessPoint), ports (state, speed, PoE),
    radios, firmware version and update flag, and provisioning timestamps.
    `device` is the Integration device id or the MAC address.
    """
    device_id, err = await _resolve_device_id(client, device)
    if err:
        return err
    details = await _fetch_details(client, device_id)
    if details is None:
        return _not_found(device)
    return _format_device(details)


async def list_pending_devices(client: UnifiClient) -> list[dict]:
    """List devices waiting to be adopted (Integration API, console-wide)."""
    items = await client.get_all_pages(_BASE + "/pending-devices")
    return [
        {
            "mac": d.get("macAddress", ""),
            "ip": d.get("ipAddress", ""),
            "model": d.get("model", ""),
            "state": d.get("state", ""),
            "supported": d.get("supported"),
            "firmware_version": d.get("firmwareVersion", ""),
            "firmware_updatable": d.get("firmwareUpdatable"),
            "features": d.get("features", []),
            "adoption_target_site_ids": d.get("adoptionTargetSiteIds", []),
        }
        for d in items
        if isinstance(d, dict)
    ]


async def _connected_client_name(client: UnifiClient, device_mac: str, port_idx: int) -> str | None:
    """Best effort: name of the client plugged into a switch port (legacy stat/sta)."""
    try:
        response = await client.get(
            "/proxy/network/api/s/{site}/stat/sta",
            cache_category="clients", cache_ttl=15.0,
        )
    except Exception:  # noqa: BLE001 (preview must never fail on this lookup)
        return None
    rows = response.get("data", []) if isinstance(response, dict) else response
    for c in rows if isinstance(rows, list) else []:
        if (
            isinstance(c, dict)
            and str(c.get("sw_mac", "")).lower() == device_mac.lower()
            and c.get("sw_port") == port_idx
        ):
            return c.get("name") or c.get("hostname") or c.get("mac")
    return None


async def _preview_power_cycle(client: UnifiClient, device: str, device_id: str, port_idx: int) -> dict:
    details = await _fetch_details(client, device_id)
    if details is None:
        return _not_found(device)
    ports = (details.get("interfaces") or {}).get("ports", []) or []
    port = next((p for p in ports if p.get("idx") == port_idx), None)
    if port is None:
        return validation_error(
            f"Port {port_idx} does not exist on {details.get('name') or device_id}."
        )
    if not isinstance(port.get("poe"), dict):
        return validation_error(
            f"Port {port_idx} on {details.get('name') or device_id} is not PoE-capable."
        )
    name = details.get("name") or device_id
    if port["poe"].get("enabled") is False:
        return validation_error(
            f"PoE is disabled on port {port_idx} of {name}; there is nothing to power cycle."
        )
    poe_down = str(port["poe"].get("state", "")).upper() == "DOWN"
    connected = await _connected_client_name(client, details.get("macAddress", ""), port_idx)
    target = f" ({connected})" if connected else ""
    return {
        "preview": True,
        "action": "power_cycle_port",
        "device": device,
        "device_id": device_id,
        "device_name": name,
        "port_idx": port_idx,
        "poe": _format_port(port).get("poe"),
        "connected": connected,
        "impact": (
            f"The device powered by port {port_idx} on {name}{target} will lose power "
            "and reboot. Anything running on it is interrupted until it boots again."
        ),
        "message": (
            f"Will power cycle PoE port {port_idx} on {name}. "
            "Call again with confirm=True to execute."
        ),
        **(
            {"warning": "The port reports PoE state DOWN, so no device is drawing power "
                        "and the cycle will probably do nothing."}
            if poe_down else {}
        ),
    }


async def power_cycle_port(
    client: UnifiClient,
    device: str,
    port_idx: int,
    confirm: bool = False,
) -> dict:
    """Power cycle (PoE off then on) one switch port to reboot the device on it.

    Use to recover a hung camera, AP or other PoE device. `device` is the
    switch's Integration id or MAC; `port_idx` is the 1-based port number.
    The powered device loses power and reboots. Requires confirm=True after
    previewing.
    """
    if isinstance(port_idx, bool) or not isinstance(port_idx, int) or port_idx < 1:
        return validation_error("port_idx must be a positive integer (1-based port number).")
    device_id, err = await _resolve_device_id(client, device)
    if err:
        return err
    if not confirm:
        return await _preview_power_cycle(client, device, device_id, port_idx)

    response = await client.post(
        f"{_DEVICES}/{device_id}/interfaces/ports/{port_idx}/actions",
        json={"action": "POWER_CYCLE"},
    )
    client.invalidate_cache("devices")
    if isinstance(response, dict) and response.get("data") == []:
        return {
            "executed": False,
            "action": "power_cycle_port",
            "response": response,
            "message": "UniFi returned an empty result; the power cycle may not have run.",
        }
    return {"executed": True, "action": "power_cycle_port", "response": response}


TOOLS = [get_device_statistics, get_device_details_v1, list_pending_devices, power_cycle_port]
