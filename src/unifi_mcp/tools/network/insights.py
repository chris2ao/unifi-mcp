"""Network insight tools (Tier 1, read-only): dashboard, speed tests, WAN status.

Endpoints:
- GET /proxy/network/v2/api/site/{site}/aggregated-dashboard
- GET /proxy/network/v2/api/site/{site}/speedtest   (timestampFrom / timestampTo, epoch ms)
- GET /proxy/network/v2/api/site/{site}/wan/load-balancing/status
- GET /proxy/network/integration/v1/sites/{site_id}/wans

The dashboard payload is several megabytes of histories, so these tools
summarize each section instead of returning it raw.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError
from unifi_mcp.validation import check_range, validation_error

GROUP = "insights"
TIER2_TOOLS: dict[str, str] = {}

DASHBOARD_PATH = "/proxy/network/v2/api/site/{site}/aggregated-dashboard"
SPEEDTEST_PATH = "/proxy/network/v2/api/site/{site}/speedtest"
WAN_LB_PATH = "/proxy/network/v2/api/site/{site}/wan/load-balancing/status"
WANS_PATH = "/proxy/network/integration/v1/sites/{site_id}/wans"
_WAN_RE = re.compile(r"[A-Za-z0-9_ .-]{1,40}")
TOP_N = 5


def _iso(ms: Any) -> str | None:
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _items(response: Any) -> list[dict]:
    raw = response.get("data", []) if isinstance(response, dict) else response
    return [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []


def _section(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _list(value) -> list:
    """Return value when it is a list, else an empty list (unexpected shapes are skipped)."""
    return value if isinstance(value, list) else []


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _wifi_doctor(data: dict) -> dict:
    doc = _section(data, "wifi_doctor")
    actions = [a for a in doc.get("actions") or [] if isinstance(a, dict)]
    return {
        "optimization_in_progress": bool(doc.get("in_progress")),
        "pending_actions": [a.get("id") for a in actions if a.get("optimization_status") == "PENDING"],
        "completed_actions": [a.get("id") for a in actions if a.get("optimization_status") == "COMPLETED"],
    }


def _isp_metrics(data: dict) -> dict:
    isp = _section(data, "isp_metrics")
    if not isp or "no_stats_reason" in isp:
        return {"available": False, "reason": isp.get("no_stats_reason", "no data")}
    scalars = {k: v for k, v in isp.items() if isinstance(v, (int, float, str, bool))}
    return {"available": True, **scalars}


def _cybersecure(data: dict) -> dict:
    cs = _section(data, "cybersecure")
    return {
        "ips_enabled": cs.get("ips_enabled"),
        "has_subscription": cs.get("has_subscription"),
        "threats": cs.get("threats"),
        "signatures": cs.get("signatures"),
        "scanned_bytes": cs.get("scanned_bytes"),
        "signatures_updated": _iso(cs.get("updated_timestamp")),
    }


def _active_clients(data: dict) -> list[dict]:
    rows = _list(_section(data, "most_active_clients").get("usage_by_client"))
    return [
        {
            "name": c.get("display_name", ""), "mac": c.get("mac", ""),
            "wired": c.get("is_wired"), "vendor": c.get("oui", ""),
            "bytes_total": c.get("total_bytes", 0),
            "bytes_rx": c.get("received_bytes", 0), "bytes_tx": c.get("transmitted_bytes", 0),
        }
        for c in rows[:TOP_N] if isinstance(c, dict)
    ]


def _active_aps(data: dict) -> list[dict]:
    rows = _list(_section(data, "most_active_aps").get("usage_by_ap"))
    return [
        {
            "name": (a.get("ap_details") or {}).get("name", ""),
            "model": (a.get("ap_details") or {}).get("model", ""),
            "mac": a.get("mac", ""), "bytes_total": a.get("total_bytes", 0),
            "satisfaction": a.get("satisfaction"),
        }
        for a in rows[:TOP_N] if isinstance(a, dict)
    ]


def _wan_group(name: str, group: dict, meta: dict) -> dict:
    hist = [h for h in group.get("history") or [] if isinstance(h, dict)]

    def col(key: str) -> list[float]:
        return [h[key] for h in hist if isinstance(h.get(key), (int, float))]

    summary = group.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    isp = meta.get("isp_name")
    return {
        "wan": name,
        "isp": isp[0] if isinstance(isp, list) and isp else isp,
        "rx_bytes": summary.get("rx_bytes"), "tx_bytes": summary.get("tx_bytes"),
        "avg_latency_ms": _avg(col("avg_latency_ms")),
        "max_latency_ms": max(col("max_latency_ms"), default=None),
        "avg_packet_loss_pct": _avg(col("avg_packet_loss_pct")),
        "peak_rx_bps": max(col("max_rx_rate_bps"), default=None),
        "peak_tx_bps": max(col("max_tx_rate_bps"), default=None),
    }


def _wan_activity(data: dict) -> list[dict]:
    act = _section(data, "wan_activity")
    meta = {g.get("name"): g for g in act.get("network_groups") or [] if isinstance(g, dict)}
    groups = act.get("activity_by_network_group")
    groups = groups if isinstance(groups, dict) else {}
    return [_wan_group(n, g, meta.get(n, {})) for n, g in groups.items() if isinstance(g, dict)]


def _wifi_connectivity(data: dict) -> list[dict]:
    rows = _list(_section(data, "wifi_connectivity").get("radio_connectivity"))
    out = []
    for r in rows:
        att = r.get("attempts") or {} if isinstance(r, dict) else {}
        out.append({
            "radio": r.get("radio_filter") if isinstance(r, dict) else None,
            "success_ratio": att.get("success_ratio"),
            "failed_connections": att.get("failed_client_connections"),
            "total_attempts": att.get("total_attempts"),
        })
    return out


def _internet(data: dict) -> dict:
    net = _section(data, "internet")
    down = [d for d in net.get("downtime_history") or [] if isinstance(d, dict)]
    health = [h for h in net.get("health_history") or [] if isinstance(h, dict)]
    latest = _section(_section(net, "speed_test"), "latest")
    return {
        "downtime_events": len(down),
        "downtime_seconds_total": sum(d.get("downtime_in_seconds", 0) or 0 for d in down),
        "recent_downtime": [
            {"wan": d.get("wan_network_group"), "at": _iso(d.get("timestamp")),
             "seconds": d.get("downtime_in_seconds")}
            for d in sorted(down, key=lambda d: d.get("timestamp") or 0, reverse=True)[:3]
        ],
        "health_samples": len(health),
        "samples_with_downtime": sum(1 for h in health if h.get("wan_downtime")),
        "samples_with_high_latency": sum(1 for h in health if h.get("high_latency")),
        "samples_with_packet_loss": sum(1 for h in health if h.get("packet_loss")),
        "service_latency_ms": {
            m.get("wan_networkgroup"): {
                s.get("service_name"): s.get("latency")
                for s in m.get("service_latencies") or [] if isinstance(s, dict)
            }
            for m in net.get("monitors") or [] if isinstance(m, dict)
        },
        "speedtest_schedule": _section(net, "speed_test").get("cron_schedule"),
        "latest_speedtest": _format_speedtest(latest) if latest else None,
    }


def _top_apps(data: dict) -> list[dict]:
    rows = _list(_section(data, "traffic_identification").get("usage_by_app"))
    return [
        {"application_id": a.get("application"), "category_id": a.get("category"),
         "bytes_total": a.get("total_bytes", 0)}
        for a in rows[:TOP_N] if isinstance(a, dict)
    ]


def summarize_dashboard(data: dict) -> dict:
    """Reduce the raw aggregated-dashboard payload to an LLM-friendly summary."""
    meta = _section(data, "dashboard_meta")
    traffic = _section(data, "traffic_identification")
    return {
        "period_start": _iso(meta.get("start_timestamp")),
        "period_end": _iso(meta.get("end_timestamp")),
        "wifi_doctor": _wifi_doctor(data),
        "isp_metrics": _isp_metrics(data),
        "cybersecure": _cybersecure(data),
        "most_active_clients": _active_clients(data),
        "most_active_aps": _active_aps(data),
        "top_apps": _top_apps(data),
        "traffic_bytes": {"rx": traffic.get("rx_bytes"), "tx": traffic.get("tx_bytes")},
        "wan_activity": _wan_activity(data),
        "upgradable_device_count": _section(data, "upgradable_device_count").get("device_count", 0),
        "wifi_connectivity": _wifi_connectivity(data),
        "internet": _internet(data),
    }


async def get_dashboard_summary(client: UnifiClient) -> dict:
    """Get a one-call health overview of the network (the UniFi dashboard, summarized).

    Use for "how is my network doing". Covers the last ~24h: WiFi Doctor
    optimization status, ISP metrics, CyberSecure (IPS threats), most active
    clients and APs, top app ids, WAN latency/loss/throughput per uplink,
    upgradable device count, WiFi connection success per radio, and internet
    downtime plus latest speed test.
    """
    response = await client.get(DASHBOARD_PATH, cache_category="insights", cache_ttl=30.0)
    if not isinstance(response, dict) or not response:
        return {"error": True, "category": "UNEXPECTED_RESPONSE",
                "message": "aggregated-dashboard returned no data.", "endpoint": DASHBOARD_PATH}
    return summarize_dashboard(response)


def _format_speedtest(r: dict) -> dict:
    return {
        "id": r.get("id", ""),
        "time": _iso(r.get("time")),
        "wan": r.get("wan_networkgroup", ""),
        "interface": r.get("interface_name", ""),
        "download_mbps": r.get("download_mbps"),
        "upload_mbps": r.get("upload_mbps"),
        "latency_ms": r.get("latency_ms"),
    }


def _speedtest_summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if (r.get("download_mbps") or 0) > 0]
    return {
        "tests": len(rows),
        "failed_or_zero": len(rows) - len(ok),
        "avg_download_mbps": _avg([r["download_mbps"] for r in ok]),
        "avg_upload_mbps": _avg([r.get("upload_mbps") or 0 for r in ok]),
        "avg_latency_ms": _avg([r.get("latency_ms") or 0 for r in ok]),
        "max_download_mbps": max((r["download_mbps"] for r in ok), default=None),
    }


def _speedtest_error(limit: Any, wan: Any, days: Any) -> dict | None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return validation_error("limit must be an integer between 1 and 200.")
    err = check_range(limit, 1, 200, "limit")
    if err:
        return err
    if wan is not None and (not isinstance(wan, str) or not _WAN_RE.fullmatch(wan)):
        return validation_error("wan must be a WAN network group such as WAN or WAN2.")
    if days is not None and (isinstance(days, bool) or not isinstance(days, int)):
        return validation_error("since_days must be an integer between 1 and 3650.")
    return check_range(days, 1, 3650, "since_days") if days is not None else None


async def get_speedtest_history(
    client: UnifiClient, limit: int = 20, wan: str | None = None, since_days: int | None = None
) -> dict:
    """Get WAN speed test history, newest first, with an average summary.

    `limit` caps results (1 to 200, default 20). `wan` filters to one uplink by
    network group name (WAN, WAN2; case-insensitive). `since_days` (1 to 3650)
    only returns tests from the last N days (server-side timestampFrom).
    A download of 0 Mbps means the test failed.
    """
    err = _speedtest_error(limit, wan, since_days)
    if err:
        return err
    path = SPEEDTEST_PATH
    if since_days is not None:
        path = f"{SPEEDTEST_PATH}?timestampFrom={int(time.time() * 1000) - int(since_days) * 86_400_000}"
    rows = _items(await client.get(path))
    if wan:
        rows = [r for r in rows if str(r.get("wan_networkgroup", "")).lower() == wan.lower()]
    rows = sorted(rows, key=lambda r: r.get("time") or 0, reverse=True)
    shown = rows[:limit]
    result = {
        "total_matching": len(rows),
        "returned": len(shown),
        "wan_filter": wan,
        "summary": _speedtest_summary(shown),
        "results": [_format_speedtest(r) for r in shown],
    }
    if not rows:
        result["message"] = "No speed test results matched."
    return result


async def _wan_names(client: UnifiClient) -> tuple[dict[str, str], str | None]:
    """Map WAN name to Integration API id; returns (mapping, warning)."""
    try:
        wans = _items(await client.get(WANS_PATH, cache_category="insights", cache_ttl=60.0))
    except UnifiError as e:
        return {}, f"WAN names unavailable: {e.message}"
    return {w["name"]: w.get("id", "") for w in wans if w.get("name")}, None


async def get_wan_status(client: UnifiClient) -> dict:
    """Get the live state of each WAN uplink (ACTIVE, BACKUP, ...) with names and ids.

    Combines load-balancing status (state per WAN network group) with the
    Integration API WAN list (name and id). Use to see which uplink carries
    traffic and which are standby or in another state.
    """
    response = await client.get(WAN_LB_PATH)
    interfaces = response.get("wan_interfaces", []) if isinstance(response, dict) else []
    ids, warning = await _wan_names(client)
    wans = [
        {"name": w.get("name", ""), "wan": w.get("wan_networkgroup", ""),
         "state": w.get("state", ""), "wan_id": ids.get(w.get("name", ""), "")}
        for w in interfaces if isinstance(w, dict)
    ]
    result = {
        "wans": wans,
        "active_wans": [w["name"] for w in wans if w["state"] == "ACTIVE"],
        "standby_wans": [w["name"] for w in wans if w["state"] == "BACKUP"],
        "other_state_wans": [w["name"] for w in wans if w["state"] not in ("ACTIVE", "BACKUP")],
    }
    if warning:
        result["warning"] = warning
    if not wans:
        result["message"] = "No WAN interfaces reported."
    return result


TOOLS = [get_dashboard_summary, get_speedtest_history, get_wan_status]
