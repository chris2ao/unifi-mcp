"""Traffic flow analysis tools (Tier 1, read-only).

Uses the v2 query endpoint:
POST /proxy/network/v2/api/site/{site}/traffic-flows

The endpoint is a read-only query (GET is 405). The body is
{timestampFrom, timestampTo (epoch ms), pageNumber, pageSize} plus optional
filters, all lists of strings except search_text:

- search_text (string, free text over IPs, names, domains, services)
- direction: local | outgoing | incoming
- protocol: UDP, TCP, ICMP, GRE, ... (upper-case IP protocol names)
- action: allowed | blocked
- risk: low | medium | high
- source_ip, destination_ip, source_mac, destination_mac, destination_domain,
  source_port, destination_port (also lists)

Volumes are large (10,000+ flows per hour; the console caps totals at 10,000),
so every tool caps the time window (7 days), page size (500) and pages
scanned. Flows come back unordered, so aggregate tools sample the first
``max_flows`` flows and report ``truncated`` when more existed.
"""

import ipaddress
import re
import time
from collections import Counter
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.validation import (
    check_enum,
    check_range,
    normalize_mac,
    validation_error,
)

GROUP = "insights"
TIER2_TOOLS: dict[str, str] = {}

FLOWS_PATH = "/proxy/network/v2/api/site/{site}/traffic-flows"
MAX_PAGE_SIZE = 500
MAX_WINDOW_MINUTES = 7 * 24 * 60
MAX_SCAN_FLOWS = 5000
DIRECTIONS = ("local", "outgoing", "incoming")
ACTIONS = ("allowed", "blocked")
RISKS = ("low", "medium", "high")
TALKER_KEYS = ("source", "destination", "service", "domain")
_PROTOCOL_RE = re.compile(r"[A-Za-z0-9_]{1,20}")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _check_int(value: Any, lo: int, hi: int, field: str) -> dict | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return validation_error(f"{field} must be an integer between {lo} and {hi}.")
    return check_range(value, lo, hi, field)


def _validate_filters(
    direction: str | None, protocol: str | None, action: str | None,
    risk: str | None, search: str | None,
) -> tuple[dict, dict | None]:
    """Return (filter body fragment, validation error or None)."""
    body: dict[str, Any] = {}
    for value, allowed, field, key in (
        (direction, DIRECTIONS, "direction", "direction"),
        (action, ACTIONS, "action", "action"),
        (risk, RISKS, "risk", "risk"),
    ):
        if value is None:
            continue
        norm = value.lower() if isinstance(value, str) else value
        err = check_enum(norm, allowed, field)
        if err:
            return {}, err
        body[key] = [norm]
    if protocol is not None:
        if not isinstance(protocol, str) or not _PROTOCOL_RE.fullmatch(protocol):
            return {}, validation_error(
                "protocol must be an IP protocol name such as TCP, UDP or ICMP."
            )
        body["protocol"] = [protocol.upper()]
    if search is not None:
        if not isinstance(search, str) or not search.strip() or len(search) > 100:
            return {}, validation_error("search must be a non-empty string of at most 100 characters.")
        body["search_text"] = search.strip()
    return body, None


async def _query(
    client: UnifiClient, minutes: int, page: int, page_size: int, filters: dict, now: int,
) -> dict:
    body = {
        **filters,
        "timestampFrom": now - minutes * 60_000,
        "timestampTo": now,
        "pageNumber": page,
        "pageSize": page_size,
    }
    response = await client.post(FLOWS_PATH, json=body)
    return response if isinstance(response, dict) else {"data": response or []}


async def _scan(client: UnifiClient, minutes: int, filters: dict, max_flows: int) -> tuple[list[dict], int, bool]:
    """Page through results until max_flows collected. Returns (flows, total, truncated)."""
    flows: list[dict] = []
    total = 0
    page = 0
    has_next = False
    now = _now_ms()  # one window for every page, so page offsets stay consistent
    while len(flows) < max_flows:
        size = min(MAX_PAGE_SIZE, max_flows - len(flows))
        response = await _query(client, minutes, page, size, filters, now)
        data = [f for f in (response.get("data") or []) if isinstance(f, dict)]
        total = response.get("total_element_count", total) or total
        flows.extend(data)
        has_next = bool(response.get("has_next")) and bool(data)
        if not has_next:
            break
        page += 1
    return flows[:max_flows], max(total, len(flows)), has_next


def _compact_flow(f: dict) -> dict:
    src, dst = f.get("source") or {}, f.get("destination") or {}
    td = f.get("traffic_data") or {}
    out = {
        "time": f.get("flow_start_time"),
        "action": f.get("action"),
        "direction": f.get("direction"),
        "protocol": f.get("protocol"),
        "service": f.get("service", ""),
        "risk": f.get("risk"),
        "source": {
            "ip": src.get("ip"), "port": src.get("port"),
            "name": src.get("device_name", ""), "mac": src.get("mac", ""),
            "zone": src.get("zone_name", ""),
        },
        "destination": {
            "ip": dst.get("ip"), "port": dst.get("port"),
            "domains": (dst.get("domains") or [])[:3],
            "zone": dst.get("zone_name", ""), "region": dst.get("region", ""),
        },
        "bytes_total": td.get("bytes_total", 0),
        "bytes_tx": td.get("bytes_tx", 0),
        "bytes_rx": td.get("bytes_rx", 0),
        "packets_total": td.get("packets_total", 0),
        "duration_ms": f.get("duration_milliseconds", 0),
        "policies": [p.get("type") for p in f.get("policies") or [] if isinstance(p, dict)],
    }
    net = (f.get("in") or {}).get("network_name")
    if net:
        out["network_in"] = net
    net_out = (f.get("out") or {}).get("network_name")
    if net_out:
        out["network_out"] = net_out
    return out


def _by_recent(flows: list[dict]) -> list[dict]:
    return sorted(flows, key=lambda f: f.get("flow_start_time") or 0, reverse=True)


def _flows_result(flows: list[dict], total: int, minutes: int, limit: int, **extra: Any) -> dict:
    shown = [_compact_flow(f) for f in _by_recent(flows)[:limit]]
    result = {
        "window_minutes": minutes,
        "total_matching": total,
        "returned": len(shown),
        "flows": shown,
        **extra,
    }
    if total >= 10_000:
        result["note"] = "The console caps flow totals at 10,000, so total_matching may be a lower bound."
    if not shown:
        result["message"] = "No flows matched in this time window."
    return result


def _check_window_limit(minutes: Any, limit: Any, max_limit: int = MAX_PAGE_SIZE) -> dict | None:
    return (
        _check_int(minutes, 1, MAX_WINDOW_MINUTES, "minutes")
        or _check_int(limit, 1, max_limit, "limit")
    )


async def list_traffic_flows(
    client: UnifiClient,
    minutes: int = 60,
    limit: int = 50,
    direction: str | None = None,
    protocol: str | None = None,
    action: str | None = None,
    risk: str | None = None,
    search: str | None = None,
) -> dict:
    """List recent network traffic flows (per-connection records), sorted newest first.

    The console returns flows unordered, so on a busy network this is the newest
    of a sample of up to `limit` matching flows, not guaranteed the newest overall.

    Use to inspect what connections happened in the last `minutes` (1 to 10080,
    default 60). `limit` caps flows returned (1 to 500, default 50). Optional
    filters: direction (local|outgoing|incoming), protocol (TCP, UDP, ICMP...),
    action (allowed|blocked), risk (low|medium|high), search (free text over
    IPs, device names, domains, services). Each flow is compact with bytes_*,
    source and destination.
    """
    err = _check_window_limit(minutes, limit)
    filters, ferr = _validate_filters(direction, protocol, action, risk, search)
    if err or ferr:
        return err or ferr
    flows, total, _ = await _scan(client, minutes, filters, limit)
    return _flows_result(flows, total, minutes, limit)


def _talker_keys(flow: dict, by: str) -> list[tuple[str, str]]:
    """Return (key, label) pairs this flow contributes to for the grouping."""
    src, dst = flow.get("source") or {}, flow.get("destination") or {}
    if by == "source":
        return [(src.get("ip") or "unknown", src.get("device_name") or "")]
    if by == "destination":
        domains = dst.get("domains") or []
        return [(dst.get("ip") or "unknown", domains[0] if domains else "")]
    if by == "service":
        return [(flow.get("service") or "OTHER", "")]
    return [(d, "") for d in (dst.get("domains") or [])]


def _aggregate(flows: list[dict], by: str) -> list[dict]:
    totals: dict[str, dict] = {}
    for flow in flows:
        td = flow.get("traffic_data") or {}
        for key, label in _talker_keys(flow, by):
            entry = totals.setdefault(
                key, {"key": key, "name": label, "flows": 0, "bytes_total": 0, "bytes_tx": 0, "bytes_rx": 0}
            )
            entry["flows"] += 1
            entry["bytes_total"] += td.get("bytes_total", 0) or 0
            entry["bytes_tx"] += td.get("bytes_tx", 0) or 0
            entry["bytes_rx"] += td.get("bytes_rx", 0) or 0
            if label and not entry["name"]:
                entry["name"] = label
    return sorted(totals.values(), key=lambda e: e["bytes_total"], reverse=True)


async def get_top_talkers(
    client: UnifiClient,
    minutes: int = 60,
    limit: int = 10,
    by: str = "source",
    max_flows: int = 2000,
) -> dict:
    """Rank top traffic talkers by bytes over the last `minutes` (default 60).

    `by` groups by source (client IP), destination (remote IP), service
    (HTTPS, DNS...) or domain. Aggregates bytes_total client-side over up to
    `max_flows` sampled flows (100 to 5000, default 2000); the result reports
    flows_scanned and truncated so totals are a sample when truncated is true.
    `limit` is how many rows to return (1 to 100).
    """
    err = (
        check_enum(by, TALKER_KEYS, "by")
        or _check_int(minutes, 1, MAX_WINDOW_MINUTES, "minutes")
        or _check_int(limit, 1, 100, "limit")
        or _check_int(max_flows, 100, MAX_SCAN_FLOWS, "max_flows")
    )
    if err:
        return err
    flows, total, truncated = await _scan(client, minutes, {}, max_flows)
    rows = _aggregate(flows, by)
    return {
        "by": by,
        "window_minutes": minutes,
        "flows_scanned": len(flows),
        "total_flows_in_window": total,
        "truncated": truncated,
        "top": rows[:limit],
        **({"message": "No flows in this time window."} if not flows else {}),
    }


async def filter_flows_by_app(
    client: UnifiClient, app_name: str, minutes: int = 60, limit: int = 50
) -> dict:
    """Find traffic flows for an application, service or domain by name.

    `app_name` is a free-text search (for example "google", "netflix", "dns",
    "youtube.com") matched by the console against service, domains, and
    device names. Window `minutes` (1 to 10080, default 60); `limit` 1 to 500.
    """
    err = _check_window_limit(minutes, limit)
    filters, ferr = _validate_filters(None, None, None, None, app_name)
    if err or ferr:
        return err or ferr
    flows, total, _ = await _scan(client, minutes, filters, limit)
    return _flows_result(flows, total, minutes, limit, app_name=app_name)


def _client_filters(client_ip: str | None, client_mac: str | None) -> tuple[list[dict], dict | None]:
    """Build the per-direction filter bodies for a client lookup."""
    if not client_ip and not client_mac:
        return [], validation_error("Provide client_ip or client_mac.")
    sides = [("source_", {}), ("destination_", {})]
    if client_ip:
        try:
            ip = str(ipaddress.ip_address(client_ip.strip()))
        except ValueError:
            return [], validation_error(f"client_ip is not a valid IP address: {client_ip!r}.")
        sides = [(p, {**f, f"{p}ip": [ip]}) for p, f in sides]
    if client_mac:
        try:
            mac = normalize_mac(client_mac)
        except ValueError:
            return [], validation_error(f"client_mac is not a valid MAC address: {client_mac!r}.")
        sides = [(p, {**f, f"{p}mac": [mac]}) for p, f in sides]
    return [f for _, f in sides], None


async def filter_flows_by_client(
    client: UnifiClient,
    client_ip: str | None = None,
    client_mac: str | None = None,
    minutes: int = 60,
    limit: int = 50,
) -> dict:
    """Find traffic flows to or from one client, by IP address or MAC address.

    Provide `client_ip` (for example 10.0.0.11) and/or `client_mac`. Matches
    the client as source or destination, sorted newest first (a sample, since
    the console returns flows unordered). Window `minutes`
    (1 to 10080, default 60); `limit` 1 to 500.
    """
    err = _check_window_limit(minutes, limit)
    bodies, cerr = _client_filters(client_ip, client_mac)
    if err or cerr:
        return err or cerr
    merged: dict[str, dict] = {}
    total = 0
    for body in bodies:
        flows, count, _ = await _scan(client, minutes, body, limit)
        total += count
        for i, f in enumerate(flows):
            merged.setdefault(f.get("id") or f"{len(merged)}-{i}", f)
    target = {"client_ip": client_ip, "client_mac": client_mac}
    return _flows_result(list(merged.values()), total, minutes, limit, client=target)


async def get_blocked_flows(client: UnifiClient, minutes: int = 60, limit: int = 50) -> dict:
    """List flows the firewall or threat engine blocked, sorted newest first (a sample).

    Use to see what was denied (policy blocks, IPS, ad blocking, content
    filtering). Window `minutes` (1 to 10080, default 60); `limit` 1 to 500.
    """
    err = _check_window_limit(minutes, limit)
    if err:
        return err
    flows, total, _ = await _scan(client, minutes, {"action": ["blocked"]}, limit)
    return _flows_result(flows, total, minutes, limit)


async def get_flow_summary(client: UnifiClient, minutes: int = 60) -> dict:
    """Summarize traffic over the last `minutes` (1 to 10080, default 60).

    Returns counts by action, risk, direction and protocol, the top services
    by flow count and bytes, and total bytes, computed over up to 2000 sampled
    flows (see flows_scanned and truncated). Use as a first look before
    drilling in with list_traffic_flows or get_top_talkers.
    """
    err = _check_int(minutes, 1, MAX_WINDOW_MINUTES, "minutes")
    if err:
        return err
    flows, total, truncated = await _scan(client, minutes, {}, 2000)
    services = Counter(f.get("service") or "OTHER" for f in flows)
    return {
        "window_minutes": minutes,
        "flows_scanned": len(flows),
        "total_flows_in_window": total,
        "truncated": truncated,
        "bytes_total": sum((f.get("traffic_data") or {}).get("bytes_total", 0) or 0 for f in flows),
        "by_action": dict(Counter(f.get("action") or "unknown" for f in flows)),
        "by_risk": dict(Counter(f.get("risk") or "unknown" for f in flows)),
        "by_direction": dict(Counter(f.get("direction") or "unknown" for f in flows)),
        "by_protocol": dict(Counter(f.get("protocol") or "unknown" for f in flows)),
        "top_services": [{"service": s, "flows": n} for s, n in services.most_common(10)],
    }


TOOLS = [
    list_traffic_flows,
    get_top_talkers,
    filter_flows_by_app,
    filter_flows_by_client,
    get_blocked_flows,
    get_flow_summary,
]
