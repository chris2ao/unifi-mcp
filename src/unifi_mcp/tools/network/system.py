"""System information, health, alarms, and System Log event tools.

UniFi Network 10.6 serves the System Log at
`POST /v2/api/site/{site}/system-log/all` (paged events) and
`POST /v2/api/site/{site}/system-log/count` (aggregate counts). The older
`system-log/{triggers,threats}` paths and legacy `stat/alarm` return 404 on
10.6.106, so events and alarms are both built on `system-log/all`.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.validation import check_range, validation_error

# No Tier 2 tools: everything here is read-only.
TIER2_TOOLS: dict[str, str] = {}

# Accepted enum values, read from the console's own 400 error message on
# Network 10.6.106 (sending an invalid value lists every accepted one).
SYSTEM_LOG_CATEGORIES: tuple[str, ...] = (
    "AUDIT", "CLIENT_DEVICES", "INTERNET_AND_WAN", "POWER", "SECURITY",
    "SOFTWARE_UPDATES", "UNIFI_DEVICES", "UNIFI_ETHERNET_PORTS", "UNKNOWN", "VPN",
)
# Ordered lowest to highest. Live data: HIGH and VERY_HIGH hold threat blocks
# and WAN failovers; MEDIUM holds admin access and config changes.
SYSTEM_LOG_SEVERITIES: tuple[str, ...] = (
    "INFO", "LOW", "MEDIUM", "WARNING", "HIGH", "VERY_HIGH",
)
ALARM_SEVERITIES: tuple[str, ...] = ("HIGH", "VERY_HIGH")

# Backward compatibility for the pre-10.6 `category` argument.
_LEGACY_CATEGORIES: dict[str, list[str]] = {"triggers": [], "threats": ["SECURITY"]}

MAX_EVENT_LIMIT = 1000
MAX_EVENT_HOURS = 2160  # 90 days
MAX_PAGE = 100_000
_HOUR_MS = 3_600_000
_MAX_PARAM_TEXT = 64
_PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")
_SYSLOG_ALL = "/proxy/network/v2/api/site/{site}/system-log/all"
_SYSLOG_COUNT = "/proxy/network/v2/api/site/{site}/system-log/count"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_utc(ms: Any) -> str | None:
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _format_uptime(seconds: int) -> str:
    """Convert seconds to human-readable uptime string."""
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


# --- validation helpers ---

def _check_int(value: Any, lo: int, hi: int, field: str) -> dict | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return validation_error(f"{field} must be an integer between {lo} and {hi}.")
    return check_range(value, lo, hi, field)


def _normalize_enum_list(
    values: Any, allowed: tuple[str, ...], field: str,
) -> tuple[list[str], dict | None]:
    """Uppercase, dedupe (order kept) and validate a list of enum strings."""
    if values is None:
        return [], None
    items = [values] if isinstance(values, str) else values
    if not isinstance(items, (list, tuple)):
        return [], validation_error(f"{field} must be a list of strings.")
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or item.upper() not in allowed:
            return [], validation_error(
                f"{field} values must be from: {', '.join(allowed)}. Got: {item!r}."
            )
        if item.upper() not in result:
            result = [*result, item.upper()]
    return result, None


def _filters(categories: Any, severities: Any) -> tuple[dict, dict | None]:
    cats, err = _normalize_enum_list(categories, SYSTEM_LOG_CATEGORIES, "categories")
    if err:
        return {}, err
    sevs, err = _normalize_enum_list(severities, SYSTEM_LOG_SEVERITIES, "severities")
    if err:
        return {}, err
    filters = {}
    if cats:
        filters["categories"] = cats
    if sevs:
        filters["severities"] = sevs
    return filters, None


def _window(hours: float) -> dict:
    now = _now_ms()
    return {"timestampFrom": now - int(hours * _HOUR_MS), "timestampTo": now}


# --- response shaping ---

def _param_text(param: Any) -> str | None:
    if not isinstance(param, dict):
        return None
    text = param.get("name") or param.get("id")
    if text is None:
        return None
    # Names can be attacker-controlled (client hostnames): strip control
    # characters and cap length so they cannot smuggle long instructions.
    cleaned = "".join(ch if ch.isprintable() else " " for ch in str(text))
    cleaned = " ".join(cleaned.split())[:_MAX_PARAM_TEXT]
    return f"({cleaned})" if param.get("enclosed_with_brackets") else cleaned


def _render(template: Any, params: dict) -> str | None:
    """Substitute {PLACEHOLDER} tokens; unknown tokens are left as-is."""
    if not isinstance(template, str):
        return None

    def _sub(match: re.Match) -> str:
        text = _param_text(params.get(match.group(1)))
        return text if text is not None else match.group(0)

    return _PLACEHOLDER_RE.sub(_sub, template)


def _target(event: dict, params: dict) -> dict | None:
    kind = event.get("target")
    if not kind or not isinstance(kind, str):
        return None
    param = params.get(kind)
    summary = {"type": kind}
    if isinstance(param, dict):
        summary = {
            **summary,
            **{k: param[k] for k in ("id", "name", "ip", "model") if param.get(k) is not None},
        }
    return summary


def _compact_event(event: dict) -> dict:
    params = event.get("parameters")
    params = params if isinstance(params, dict) else {}
    return {
        "id": event.get("id"),
        "time": _iso_utc(event.get("timestamp")),
        "category": event.get("category"),
        "subcategory": event.get("subcategory"),
        "severity": event.get("severity"),
        "key": event.get("key"),
        "event": event.get("event"),
        "type": event.get("type"),
        "title": _render(event.get("title_raw"), params),
        "message": _render(event.get("message_raw"), params),
        "target": _target(event, params),
    }


def _unexpected(what: str) -> dict:
    return {
        "error": True,
        "category": "UNEXPECTED_RESPONSE",
        "message": (
            f"The console returned an unexpected response for {what}. This "
            "does not mean there are no events; the System Log endpoint may "
            "have changed on this firmware."
        ),
    }


def _event_list(response: Any) -> list[dict] | None:
    """Return the event dicts, or None when the response has an unknown shape."""
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        items = response.get("data")
    else:
        items = None
    if not isinstance(items, list):
        return None
    return [e for e in items if isinstance(e, dict)]


async def _query_events(
    client: UnifiClient, hours: float, limit: int, page: int, filters: dict,
) -> list[dict]:
    body = {**_window(hours), "pageNumber": page, "pageSize": limit, **filters}
    response = await client.post(_SYSLOG_ALL, json=body)
    events = _event_list(response)
    if events is None:
        return [_unexpected("system-log/all")]
    return [_compact_event(e) for e in events[:limit]]


def _validate_window(limit: Any, hours: Any, page: Any) -> dict | None:
    return (
        _check_int(limit, 1, MAX_EVENT_LIMIT, "limit")
        or check_range(hours, 1, MAX_EVENT_HOURS, "hours")
        or _check_int(page, 0, MAX_PAGE, "page")
    )


# --- tools ---

async def get_system_info(client: UnifiClient) -> dict:
    """Get UniFi controller system information including version, hostname, and uptime."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/sysinfo",
        cache_category="system", cache_ttl=120.0,
    )
    info = response["data"][0]
    return {
        "hostname": info.get("hostname", ""),
        "name": info.get("name", ""),
        "version": info.get("version", ""),
        "build": info.get("build", ""),
        "timezone": info.get("timezone", ""),
        "uptime": info.get("uptime", 0),
        "uptime_human": _format_uptime(info.get("uptime", 0)),
        "update_available": info.get("update_available", False),
        "autobackup": info.get("autobackup", False),
    }


async def get_health(client: UnifiClient) -> list[dict]:
    """Get health status for all subsystems (WAN, WLAN, LAN, VPN)."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/health",
        cache_category="system", cache_ttl=30.0,
    )
    return response["data"]


async def get_alarms(
    client: UnifiClient, hours: float = 168, limit: int = 50,
) -> list[dict]:
    """Get recent alarms: HIGH and VERY_HIGH severity System Log events (threats blocked, WAN failover, outages).

    Network 10.6 removed the legacy alarm list, so alarms are the high-severity
    System Log entries. hours: look-back window in hours (1 to 2160, default
    168 = 7 days). limit: max alarms returned (1 to 1000), newest first. Each
    item has the same compact shape as get_events.
    """
    err = _validate_window(limit, hours, 0)
    if err:
        return [err]
    return await _query_events(
        client, hours, limit, 0, {"severities": list(ALARM_SEVERITIES)},
    )


async def get_events(
    client: UnifiClient,
    limit: int = 50,
    hours: float = 24,
    categories: list[str] | None = None,
    severities: list[str] | None = None,
    page: int = 0,
    category: str | None = None,
) -> list[dict]:
    """Get UniFi Network System Log events (client connects, threats, admin access, WAN, updates), newest first.

    hours: look-back window in hours (1 to 2160). limit: page size and max
    events returned (1 to 1000). page: 0-based page for older events.
    categories: any of AUDIT, CLIENT_DEVICES, INTERNET_AND_WAN, POWER, SECURITY,
    SOFTWARE_UPDATES, UNIFI_DEVICES, UNIFI_ETHERNET_PORTS, UNKNOWN, VPN.
    severities: any of INFO, LOW, MEDIUM, WARNING, HIGH, VERY_HIGH. category:
    deprecated, "threats" equals categories=["SECURITY"] and "triggers" means
    all; ignored when categories is given. Returns a list of compact events:
    id, time (ISO 8601 UTC), category, subcategory, severity, key, event, type,
    title, message (rendered text) and target ({type, id, name, ip}). Use
    get_event_counts for totals in a window.
    """
    if category is not None and category not in _LEGACY_CATEGORIES:
        return [validation_error(
            f"category must be one of {sorted(_LEGACY_CATEGORIES)} (deprecated; "
            "use categories instead)."
        )]
    err = _validate_window(limit, hours, page)
    if err:
        return [err]
    if categories is None and category is not None:
        categories = _LEGACY_CATEGORIES[category]
    filters, err = _filters(categories, severities)
    if err:
        return [err]
    return await _query_events(client, hours, limit, page, filters)


def _count_map(entries: Any) -> dict[str, int]:
    if not isinstance(entries, list):
        return {}
    pairs = [
        (e.get("name"), e.get("count")) for e in entries if isinstance(e, dict)
    ]
    valid = [
        (name, count) for name, count in pairs
        if isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool)
    ]
    return dict(sorted(valid, key=lambda p: (-p[1], p[0])))


async def get_event_counts(
    client: UnifiClient,
    hours: float = 24,
    categories: list[str] | None = None,
    severities: list[str] | None = None,
) -> dict:
    """Count System Log events in a time window, grouped by category, event name and coarse type.

    Use for a quick overview before paging through get_events. hours: look-back
    window (1 to 2160). Optional categories / severities filters take the same
    values as get_events. Returns {hours, time_from, time_to, total,
    by_category, by_event, by_type}, each map sorted by count descending.
    by_event keys match each event's `event` field in get_events (for example
    CLIENT_CONNECTED_WIRELESS), not its `key` field. by_type is a coarse
    AUDIT/GENERAL split and does not match the per-event `type` field.
    """
    err = check_range(hours, 1, MAX_EVENT_HOURS, "hours")
    if err:
        return err
    filters, err = _filters(categories, severities)
    if err:
        return err
    window = _window(hours)
    response = await client.post(_SYSLOG_COUNT, json={**window, **filters})
    if not isinstance(response, dict) or not any(
        k in response for k in ("categories", "events", "type")
    ):
        return _unexpected("system-log/count")
    data = response
    by_category = _count_map(data.get("categories"))
    return {
        "hours": hours,
        "time_from": _iso_utc(window["timestampFrom"]),
        "time_to": _iso_utc(window["timestampTo"]),
        "total": sum(by_category.values()),
        "by_category": by_category,
        "by_event": _count_map(data.get("events")),
        "by_type": _count_map(data.get("type")),
    }


TOOLS = [get_system_info, get_health, get_alarms, get_events, get_event_counts]
