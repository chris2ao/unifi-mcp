"""WiFi/SSID management tools: list, create, update, delete, stats, toggle."""

from unifi_mcp.auth.client import UnifiClient


def _format_wlan(w: dict) -> dict:
    return {
        "id": w.get("_id", ""),
        "name": w.get("name", ""),
        "enabled": w.get("enabled", True),
        "security": w.get("security", ""),
        "wlan_band": w.get("wlan_band", ""),
        "networkconf_id": w.get("networkconf_id", ""),
        "hide_ssid": w.get("hide_ssid", False),
        "is_guest": w.get("is_guest", False),
        "num_sta": w.get("num_sta", 0),
    }


async def list_wlans(client: UnifiClient) -> list[dict]:
    """List all configured wireless networks (SSIDs)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/wlanconf",
        cache_category="wifi", cache_ttl=30.0,
    )
    return [_format_wlan(w) for w in response["data"]]


async def create_wlan(
    client: UnifiClient,
    name: str,
    security: str = "wpapsk",
    passphrase: str = "",
    wlan_band: str = "both",
    networkconf_id: str = "",
    hide_ssid: bool = False,
    guest_mode: bool = False,
    confirm: bool = False,
) -> dict:
    """Create a new wireless network. Requires confirm=True after previewing."""
    payload = {
        "name": name,
        "security": security,
        "wlan_band": wlan_band,
        "hide_ssid": hide_ssid,
    }
    if passphrase:
        payload["x_passphrase"] = passphrase
    if networkconf_id:
        payload["networkconf_id"] = networkconf_id
    if guest_mode:
        payload["is_guest"] = True

    if not confirm:
        # Do not include passphrase in preview for security
        preview_params = {k: v for k, v in payload.items() if k != "x_passphrase"}
        return {
            "preview": True,
            "action": "create_wlan",
            "params": preview_params,
            "message": f"Will create SSID '{name}'. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/rest/wlanconf",
        json=payload,
    )
    client.invalidate_cache("wifi")
    return {"executed": True, "action": "create_wlan", "response": response}


async def update_wlan(
    client: UnifiClient,
    wlan_id: str,
    updates: dict,
    confirm: bool = False,
) -> dict:
    """Update an existing wireless network. Requires confirm=True after previewing."""
    if not confirm:
        # Strip passphrase from preview to avoid leaking secrets
        safe_updates = {k: v for k, v in updates.items() if k != "x_passphrase"}
        return {
            "preview": True,
            "action": "update_wlan",
            "wlan_id": wlan_id,
            "updates": safe_updates,
            "message": f"Will update SSID {wlan_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/wlanconf/{wlan_id}",
        json=updates,
    )
    client.invalidate_cache("wifi")
    return {"executed": True, "action": "update_wlan", "response": response}


async def delete_wlan(client: UnifiClient, wlan_id: str, confirm: bool = False) -> dict:
    """Delete a wireless network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "delete_wlan",
            "wlan_id": wlan_id,
            "message": f"Will delete SSID {wlan_id}. This is irreversible. Call again with confirm=True to execute.",
        }

    response = await client.delete(
        f"/proxy/network/api/s/{{site}}/rest/wlanconf/{wlan_id}",
    )
    client.invalidate_cache("wifi")
    return {"executed": True, "action": "delete_wlan", "response": response}


async def get_wlan_stats(client: UnifiClient) -> dict:
    """Get per-SSID client statistics (aggregated from active clients)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/sta",
        cache_category="clients", cache_ttl=15.0,
    )
    stats: dict[str, dict] = {}
    for c in response["data"]:
        ssid = c.get("essid", "")
        if not ssid:
            continue
        if ssid not in stats:
            stats[ssid] = {"client_count": 0, "tx_bytes": 0, "rx_bytes": 0}
        stats[ssid]["client_count"] += 1
        stats[ssid]["tx_bytes"] += c.get("tx_bytes", 0)
        stats[ssid]["rx_bytes"] += c.get("rx_bytes", 0)
    return stats


async def toggle_wlan(
    client: UnifiClient,
    wlan_id: str,
    enabled: bool,
    confirm: bool = False,
) -> dict:
    """Enable or disable a wireless network. Requires confirm=True after previewing."""
    if not confirm:
        state = "enable" if enabled else "disable"
        return {
            "preview": True,
            "action": "toggle_wlan",
            "wlan_id": wlan_id,
            "enabled": enabled,
            "message": f"Will {state} SSID {wlan_id}. Call again with confirm=True to execute.",
        }

    response = await client.put(
        f"/proxy/network/api/s/{{site}}/rest/wlanconf/{wlan_id}",
        json={"enabled": enabled},
    )
    client.invalidate_cache("wifi")
    return {"executed": True, "action": "toggle_wlan", "wlan_id": wlan_id, "enabled": enabled, "response": response}


TOOLS = [list_wlans, create_wlan, update_wlan, delete_wlan, get_wlan_stats, toggle_wlan]
