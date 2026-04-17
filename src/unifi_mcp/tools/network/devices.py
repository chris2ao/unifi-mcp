"""Device management tools: list, get, restart, adopt, forget, locate, RF scan, firmware, rename, stats, ports, uplinks."""

from unifi_mcp.auth.client import UnifiClient


def _format_bytes(b: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _format_uptime(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"


def _format_device(d: dict) -> dict:
    return {
        "id": d.get("_id", ""),
        "mac": d.get("mac", ""),
        "name": d.get("name", d.get("mac", "")),
        "model": d.get("model", ""),
        "type": d.get("type", ""),
        "ip": d.get("ip", ""),
        "version": d.get("version", ""),
        "upgradable": d.get("upgradable", False),
        "state": "online" if d.get("state") == 1 else "offline",
        "adopted": d.get("adopted", False),
        "uptime": d.get("uptime", 0),
        "uptime_human": _format_uptime(d.get("uptime", 0)),
        "clients": d.get("num_sta", 0),
        "tx_bytes": d.get("tx_bytes", 0),
        "tx_human": _format_bytes(d.get("tx_bytes", 0)),
        "rx_bytes": d.get("rx_bytes", 0),
        "rx_human": _format_bytes(d.get("rx_bytes", 0)),
    }


async def list_devices(client: UnifiClient) -> list[dict]:
    """List all network devices (APs, switches, gateways) with status and stats."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/device",
        cache_category="devices", cache_ttl=30.0,
    )
    return [_format_device(d) for d in response["data"]]


async def get_device(client: UnifiClient, mac: str) -> dict:
    """Get detailed information for a specific device by MAC address."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/device/{mac}",
        cache_category="devices", cache_ttl=30.0,
    )
    return _format_device(response["data"][0])


async def restart_device(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Restart a network device. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "restart_device",
            "mac": mac,
            "message": f"Will restart device {mac}. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/devmgr",
        json={"cmd": "restart", "mac": mac},
    )
    client.invalidate_cache("devices")
    return {"executed": True, "action": "restart_device", "mac": mac, "response": response}


async def adopt_device(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Adopt a new device into the network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "adopt_device",
            "mac": mac,
            "message": f"Will adopt device {mac}. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/devmgr",
        json={"cmd": "adopt", "mac": mac},
    )
    client.invalidate_cache("devices")
    return {"executed": True, "action": "adopt_device", "mac": mac, "response": response}


async def forget_device(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Remove a device from the network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "forget_device",
            "mac": mac,
            "message": f"Will forget device {mac}. This removes it from the controller. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/devmgr",
        json={"cmd": "delete", "mac": mac},
    )
    client.invalidate_cache("devices")
    return {"executed": True, "action": "forget_device", "mac": mac, "response": response}


async def locate_device(client: UnifiClient, mac: str, enabled: bool = True) -> dict:
    """Toggle the locate LED on a device (Tier 1, non-destructive)."""
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/devmgr",
        json={"cmd": "set-locate" if enabled else "unset-locate", "mac": mac},
    )
    return {"action": "locate_device", "mac": mac, "enabled": enabled, "response": response}


async def rf_scan(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Trigger an RF environment scan on an AP. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "rf_scan",
            "mac": mac,
            "message": f"Will trigger RF scan on AP {mac}. This briefly disrupts wireless. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/devmgr",
        json={"cmd": "spectrum-scan", "mac": mac},
    )
    return {"executed": True, "action": "rf_scan", "mac": mac, "response": response}


async def upgrade_firmware(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Upgrade device firmware to latest version. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "upgrade_firmware",
            "mac": mac,
            "message": f"Will upgrade firmware on device {mac}. Device will restart. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/devmgr",
        json={"cmd": "upgrade", "mac": mac},
    )
    client.invalidate_cache("devices")
    return {"executed": True, "action": "upgrade_firmware", "mac": mac, "response": response}


async def rename_device(client: UnifiClient, device_id: str, name: str) -> dict:
    """Rename a device (Tier 1, cosmetic change). Uses device _id, not MAC."""
    return await client.put(
        f"/proxy/network/api/s/{{site}}/rest/device/{device_id}",
        json={"name": name},
    )


async def get_device_stats(client: UnifiClient, mac: str) -> dict:
    """Get detailed statistics for a device (CPU, memory, throughput)."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/device/{mac}",
        cache_category="devices", cache_ttl=15.0,
    )
    d = response["data"][0]
    return {
        "mac": mac,
        "name": d.get("name", mac),
        "cpu_usage": d.get("system-stats", {}).get("cpu", "N/A"),
        "mem_usage": d.get("system-stats", {}).get("mem", "N/A"),
        "uptime": d.get("uptime", 0),
        "uptime_human": _format_uptime(d.get("uptime", 0)),
        "clients": d.get("num_sta", 0),
        "tx_bytes": d.get("tx_bytes", 0),
        "tx_human": _format_bytes(d.get("tx_bytes", 0)),
        "rx_bytes": d.get("rx_bytes", 0),
        "rx_human": _format_bytes(d.get("rx_bytes", 0)),
    }


async def get_device_ports(client: UnifiClient, mac: str) -> list[dict]:
    """Get port status for a switch device."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/device/{mac}",
        cache_category="devices", cache_ttl=15.0,
    )
    d = response["data"][0]
    ports = d.get("port_table", [])
    return [
        {
            "port": p.get("port_idx"),
            "name": p.get("name", ""),
            "enabled": p.get("enable", True),
            "speed": p.get("speed", 0),
            "is_uplink": p.get("is_uplink", False),
            "poe_mode": p.get("poe_mode", "off"),
            "poe_power": p.get("poe_power", "0"),
        }
        for p in ports
    ]


async def get_device_uplinks(client: UnifiClient, mac: str) -> dict:
    """Get uplink information for a device."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/device/{mac}",
        cache_category="devices", cache_ttl=30.0,
    )
    d = response["data"][0]
    uplinks = d.get("uplink", {})
    return {
        "mac": mac,
        "name": d.get("name", mac),
        "uplink_mac": uplinks.get("uplink_mac", ""),
        "uplink_device_name": uplinks.get("uplink_device_name", ""),
        "type": uplinks.get("type", ""),
        "speed": uplinks.get("speed", 0),
    }


TOOLS = [
    list_devices, get_device, restart_device, adopt_device, forget_device,
    locate_device, rf_scan, upgrade_firmware, rename_device,
    get_device_stats, get_device_ports, get_device_uplinks,
]
