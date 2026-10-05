"""Client management tools: list, get, block, unblock, reconnect, alias, history, list_all,
recent (offline) clients, official-API client lookup, and guest authorize/unauthorize."""

import time

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import (
    check_id, check_mac, check_range, normalize_mac, validation_error,
)

TIER2_TOOLS: dict[str, str] = {
    "block_client": "clients",
    "unblock_client": "clients",
    "authorize_guest": "clients",
    "unauthorize_guest": "clients",
}

_CLIENTS_V1 = "/proxy/network/integration/v1/sites/{site_id}/clients"
_CLIENTS_HISTORY = "/proxy/network/v2/api/site/{site}/clients/history"

# Default look-back for client history when no explicit range is given (30 days).
_HISTORY_DEFAULT_LOOKBACK_MS = 30 * 24 * 60 * 60 * 1000


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


def _format_client(c: dict) -> dict:
    return {
        "id": c.get("_id", ""),
        "mac": c.get("mac", ""),
        "hostname": c.get("hostname", ""),
        "ip": c.get("ip", ""),
        "name": c.get("name", ""),
        "network": c.get("network", ""),
        "is_wired": c.get("is_wired", False),
        "is_guest": c.get("is_guest", False),
        "uptime": c.get("uptime", 0),
        "uptime_human": _format_uptime(c.get("uptime", 0)),
        "tx_bytes": c.get("tx_bytes", 0),
        "tx_human": _format_bytes(c.get("tx_bytes", 0)),
        "rx_bytes": c.get("rx_bytes", 0),
        "rx_human": _format_bytes(c.get("rx_bytes", 0)),
        # Wired clients carry their volume under wired-* counters; /stat/sta puts
        # 0 in tx_bytes/rx_bytes for them. Surface both so callers can pick.
        "wired_tx_bytes": c.get("wired-tx_bytes", 0),
        "wired_rx_bytes": c.get("wired-rx_bytes", 0),
        "signal": c.get("signal", 0),
        "satisfaction": c.get("satisfaction", 0),
        "blocked": c.get("blocked", False),
    }


async def list_clients(client: UnifiClient) -> list[dict]:
    """List all currently connected (active) clients."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/sta",
        cache_category="clients", cache_ttl=15.0,
    )
    return [_format_client(c) for c in response["data"]]


async def get_client(client: UnifiClient, mac: str) -> dict:
    """Get details for a specific client by MAC address."""
    response = await client.get(
        f"/proxy/network/api/s/{{site}}/stat/sta/{mac}",
        cache_category="clients", cache_ttl=15.0,
    )
    return _format_client(response["data"][0])


async def block_client(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Block a client from the network. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "block_client",
            "mac": mac,
            "message": f"Will block client {mac} from the network. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/stamgr",
        json={"cmd": "block-sta", "mac": mac},
    )
    client.invalidate_cache("clients")
    return {"executed": True, "action": "block_client", "mac": mac, "response": response}


async def unblock_client(client: UnifiClient, mac: str, confirm: bool = False) -> dict:
    """Unblock a previously blocked client. Requires confirm=True after previewing."""
    if not confirm:
        return {
            "preview": True,
            "action": "unblock_client",
            "mac": mac,
            "message": f"Will unblock client {mac}. Call again with confirm=True to execute.",
        }
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/stamgr",
        json={"cmd": "unblock-sta", "mac": mac},
    )
    client.invalidate_cache("clients")
    return {"executed": True, "action": "unblock_client", "mac": mac, "response": response}


async def reconnect_client(client: UnifiClient, mac: str) -> dict:
    """Force a client to reconnect (kick and rejoin). Tier 1, non-destructive."""
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/stamgr",
        json={"cmd": "kick-sta", "mac": mac},
    )
    return {"action": "reconnect_client", "mac": mac, "response": response}


async def set_client_alias(client: UnifiClient, client_id: str, name: str) -> dict:
    """Set a friendly name (alias) for a client. Tier 1, cosmetic change."""
    return await client.put(
        f"/proxy/network/api/s/{{site}}/rest/user/{client_id}",
        json={"name": name},
    )


async def list_all_clients(client: UnifiClient) -> list[dict]:
    """List all known clients (historical, including offline)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/rest/user",
        cache_category="clients", cache_ttl=30.0,
    )
    return [
        {
            "id": c.get("_id", ""),
            "mac": c.get("mac", ""),
            "hostname": c.get("hostname", ""),
            "name": c.get("name", ""),
        }
        for c in response["data"]
    ]


_HISTORY_INTERVALS = ("hourly", "daily")


async def get_client_history(
    client: UnifiClient,
    mac: str,
    start: int | None = None,
    end: int | None = None,
    interval: str = "hourly",
) -> list[dict]:
    """Get per-client usage history at the given report interval.

    Returns one entry per bucket with ``time`` (epoch milliseconds), ``rx_bytes``
    and ``tx_bytes``. ``start``/``end`` are epoch milliseconds; when omitted the
    range defaults to the last 30 days ending now. The ``time`` attr is requested
    explicitly so each bucket is timestamped (the controller omits it otherwise).

    ``interval`` selects the controller report: ``hourly`` (retained ~7 days) or
    ``daily`` (retained ~30+ days, used for the 30-day window). Unknown values
    fall back to ``hourly``.
    """
    if interval not in _HISTORY_INTERVALS:
        interval = "hourly"
    if end is None:
        end = int(time.time() * 1000)
    if start is None:
        start = end - _HISTORY_DEFAULT_LOOKBACK_MS
    response = await client.post(
        f"/proxy/network/api/s/{{site}}/stat/report/{interval}.user",
        json={
            "attrs": ["time", "rx_bytes", "tx_bytes"],
            "start": start,
            "end": end,
            "mac": mac,
        },
    )
    return response["data"]


def _not_found(message: str, endpoint: str) -> dict:
    return {
        "error": True, "category": str(ErrorCategory.NOT_FOUND),
        "message": message, "endpoint": endpoint,
    }


def _format_client_v1(c: dict) -> dict:
    access = c.get("access") if isinstance(c.get("access"), dict) else {}
    core = {"id", "name", "type", "connectedAt", "ipAddress", "macAddress", "uplinkDeviceId", "access"}
    result = {
        "id": c.get("id", ""),
        "name": c.get("name", ""),
        "type": c.get("type", ""),
        "mac": c.get("macAddress", ""),
        "ip": c.get("ipAddress", ""),
        "connected_at": c.get("connectedAt"),
        "uplink_device_id": c.get("uplinkDeviceId"),
        "access_type": access.get("type", ""),
        "authorized": access.get("authorized"),
        "authorization": access.get("authorization"),
    }
    extra = {k: v for k, v in c.items() if k not in core}
    return {**result, "details": extra} if extra else result


async def _find_client_v1(client: UnifiClient, ident: str) -> dict | None:
    """Resolve an Integration client by id (UUID) or MAC. Returns None when absent."""
    if check_mac(ident) is None:
        mac = normalize_mac(ident)
        page = await client.get(_CLIENTS_V1, params={"filter": f"macAddress.eq('{mac}')", "limit": 1})
        items = page.get("data", []) if isinstance(page, dict) else page
        first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else None
        # Defensive: a firmware that ignores the filter would return an unrelated client.
        if first is None or normalize_mac(str(first.get("macAddress", ""))) != mac:
            return None
        return first
    try:
        found = await client.get(f"{_CLIENTS_V1}/{ident}")
    except UnifiError as e:
        if e.category == ErrorCategory.NOT_FOUND:
            return None
        raise
    return found if isinstance(found, dict) and found.get("id") else None


def _check_ident(ident: object) -> dict | None:
    if isinstance(ident, str) and check_mac(ident) is None:
        return None
    return check_id(ident, "client")


async def get_client_v1(client: UnifiClient, client_ref: str) -> dict:
    """Get a client from the official API by Integration id (UUID) or MAC.

    Returns type (WIRED, WIRELESS, VPN, TELEPORT), IP, connected_at, uplink
    device id and access info (access_type GUEST or DEFAULT, authorized flag
    and authorization details for guests).
    """
    err = _check_ident(client_ref)
    if err:
        return err
    try:
        found = await _find_client_v1(client, client_ref)
    except UnifiError as e:
        return e.to_dict()
    if found is None:
        return _not_found(f"No client found for {client_ref!r}.", _CLIENTS_V1)
    return _format_client_v1(found)


async def _resolve_guest(client: UnifiClient, ident: str) -> dict:
    """Look up a client and confirm it is a guest. Returns the client or an error dict."""
    try:
        found = await _find_client_v1(client, ident)
    except UnifiError as e:
        return e.to_dict()
    if found is None:
        return _not_found(f"No client found for {ident!r}.", _CLIENTS_V1)
    access = found.get("access") if isinstance(found.get("access"), dict) else {}
    if access.get("type") != "GUEST":
        return validation_error(
            f"Client {found.get('name') or ident!r} is not a guest (access type "
            f"{access.get('type') or 'unknown'}). Guest authorization only applies to guest clients."
        )
    return found


def _guest_limits(minutes, data_limit_mb, rx_kbps, tx_kbps) -> tuple[dict, dict | None]:
    checks = (
        ("timeLimitMinutes", minutes, 1, 1_000_000, "minutes"),
        ("dataUsageLimitMBytes", data_limit_mb, 1, 1_048_576, "data_limit_mb"),
        ("rxRateLimitKbps", rx_kbps, 2, 100_000, "rx_kbps"),
        ("txRateLimitKbps", tx_kbps, 2, 100_000, "tx_kbps"),
    )
    body: dict = {}
    for key, value, lo, hi, field in checks:
        if value is None:
            continue
        err = check_range(value, lo, hi, field)
        if err is None and int(value) != value:
            err = validation_error(f"{field} must be a whole number.")
        if err:
            return {}, err
        body = {**body, key: int(value)}
    return body, None


async def _post_guest_action(client: UnifiClient, found: dict, body: dict, action: str, expect: str) -> dict:
    response = await client.post(f"{_CLIENTS_V1}/{found['id']}/actions", json=body)
    client.invalidate_cache("clients")
    if not isinstance(response, dict) or not response.get(expect):
        return {
            "executed": False, "action": action, "client_id": found["id"], "response": response,
            "message": "The console returned no authorization details, so the change may not "
                       "have applied. Verify with get_client_v1.",
        }
    return {"executed": True, "action": action, "client_id": found["id"], "response": response}


async def authorize_guest(
    client: UnifiClient,
    client_ref: str,
    minutes: int | None = None,
    data_limit_mb: int | None = None,
    rx_kbps: int | None = None,
    tx_kbps: int | None = None,
    confirm: bool = False,
) -> dict:
    """Authorize a guest client for network access (guest portal bypass). Requires confirm=True after previewing.

    `client_ref` is the Integration client id (UUID) or the client MAC. The client
    must be a guest. Optional limits: `minutes` (1 to 1,000,000, site default
    when omitted), `data_limit_mb` (1 to 1,048,576), `rx_kbps` download and
    `tx_kbps` upload rate (2 to 100,000). Re-authorizing replaces any active
    authorization and resets the guest's traffic counters.
    """
    err = _check_ident(client_ref)
    if err:
        return err
    limits, err = _guest_limits(minutes, data_limit_mb, rx_kbps, tx_kbps)
    if err:
        return err
    found = await _resolve_guest(client, client_ref)
    if found.get("error"):
        return found
    body = {"action": "AUTHORIZE_GUEST_ACCESS", **limits}
    if not confirm:
        formatted = _format_client_v1(found)
        impact = (
            {"impact": "The guest is already authorized. Authorizing again replaces the "
                       "current authorization and resets its traffic counters."}
            if formatted.get("authorized") else {}
        )
        return {
            "preview": True,
            "action": "authorize_guest",
            "client": formatted,
            "request": body,
            **impact,
            "message": f"Will grant guest network access to {found.get('name') or client_ref}. "
                       "Call again with confirm=True to execute.",
        }
    return await _post_guest_action(client, found, body, "authorize_guest", "grantedAuthorization")


async def unauthorize_guest(client: UnifiClient, client_ref: str, confirm: bool = False) -> dict:
    """Revoke a guest client's network access and disconnect it. Requires confirm=True after previewing.

    `client_ref` is the Integration client id (UUID) or the client MAC. The client must be a guest.
    """
    err = _check_ident(client_ref)
    if err:
        return err
    found = await _resolve_guest(client, client_ref)
    if found.get("error"):
        return found
    if _format_client_v1(found).get("authorized") is False:
        return {
            "executed": False,
            "action": "unauthorize_guest",
            "client": _format_client_v1(found),
            "message": "The guest is not currently authorized, so there is nothing to revoke.",
        }
    if not confirm:
        return {
            "preview": True,
            "action": "unauthorize_guest",
            "client": _format_client_v1(found),
            "impact": "The guest is disconnected and loses network access until authorized again.",
            "message": f"Will revoke guest access for {found.get('name') or client_ref}. "
                       "Call again with confirm=True to execute.",
        }
    body = {"action": "UNAUTHORIZE_GUEST_ACCESS"}
    return await _post_guest_action(client, found, body, "unauthorize_guest", "revokedAuthorization")


def _format_recent(c: dict) -> dict:
    return {
        "id": c.get("user_id", ""),
        "mac": c.get("mac", c.get("id", "")),
        "name": c.get("display_name") or c.get("name") or c.get("hostname", ""),
        "hostname": c.get("hostname", ""),
        "type": c.get("type", ""),
        "is_wired": c.get("is_wired", False),
        "is_guest": c.get("is_guest", False),
        "blocked": c.get("blocked", False),
        "first_seen": c.get("first_seen"),
        "last_seen": c.get("last_seen"),
        "last_ip": c.get("last_ip", ""),
        "last_network": c.get("last_connection_network_name", ""),
        "last_network_id": c.get("last_connection_network_id", ""),
        "last_uplink_mac": c.get("last_uplink_mac", ""),
        "last_uplink_name": c.get("last_uplink_name", ""),
    }


async def list_recent_clients(
    client: UnifiClient, limit: int = 100, hours: int | None = None
) -> list[dict] | dict:
    """List known clients seen recently, including offline ones, newest first.

    Each entry has last network, last IP, last uplink (device name and MAC) and
    last_seen (epoch seconds). `limit` caps results (1 to 1000, default 100).
    `hours` limits to clients seen within that many hours (1 to 8760); omit it
    to include every known client.
    """
    err = check_range(limit, 1, 1000, "limit")
    if err:
        return err
    if hours is not None:
        err = check_range(hours, 1, 8760, "hours")
        if err:
            return err
    response = await client.get(
        _CLIENTS_HISTORY,
        cache_category="clients", cache_ttl=30.0,
        params={"withinHours": int(hours) if hours is not None else 0},
    )
    rows = response.get("data", []) if isinstance(response, dict) else response
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    rows = sorted(rows, key=lambda r: r.get("last_seen") or 0, reverse=True)
    return [_format_recent(r) for r in rows[: int(limit)]]


TOOLS = [
    list_clients, get_client, block_client, unblock_client,
    reconnect_client, set_client_alias, list_all_clients, get_client_history,
    list_recent_clients, get_client_v1, authorize_guest, unauthorize_guest,
]
