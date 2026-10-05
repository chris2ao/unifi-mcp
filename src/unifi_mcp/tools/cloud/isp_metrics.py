"""Site Manager ISP metrics tools (latency, packet loss, throughput, uptime history)."""

from unifi_mcp.cloud.client import CloudClient
from unifi_mcp.tools.cloud._common import (
    as_list, check_timestamp, unwrap, validation_error,
)

GROUP = "cloud"
TIER2_TOOLS: dict[str, str] = {}

METRIC_TYPES = ("5m", "1h")
DURATIONS = {"5m": ("24h",), "1h": ("7d", "30d")}
_SITE_KEYS = ("hostId", "siteId", "beginTimestamp", "endTimestamp")


def _check_type(metric_type: object) -> dict | None:
    if metric_type not in METRIC_TYPES:
        return validation_error("metric_type must be '5m' (5-minute) or '1h' (hourly)")
    return None


def _check_window(metric_type: str, duration, begin, end) -> dict | None:
    if duration is not None:
        if begin is not None or end is not None:
            return validation_error("duration cannot be combined with begin or end")
        if duration not in DURATIONS[metric_type]:
            allowed = ", ".join(DURATIONS[metric_type])
            return validation_error(f"duration for metric_type '{metric_type}' must be one of: {allowed}")
    for name, value in (("begin", begin), ("end", end)):
        if value is not None and (err := check_timestamp(value, name)):
            return err
    return None


async def get_isp_metrics(
    client: CloudClient,
    metric_type: str = "5m",
    duration: str | None = None,
    begin: str | None = None,
    end: str | None = None,
) -> list[dict] | dict:
    """Get ISP metrics (latency, packet loss, up/down kbps, uptime, downtime) for all cloud sites. metric_type '5m' (last 24h available) or '1h' (30 days). Use duration ('24h' for 5m; '7d' or '30d' for 1h) or begin/end RFC3339 timestamps, not both. Output is raw periods per site (about 720 for '1h' over 30d), so prefer short windows."""
    if (err := _check_type(metric_type)) or (err := _check_window(metric_type, duration, begin, end)):
        return err
    params = {"duration": duration, "beginTimestamp": begin, "endTimestamp": end}
    query = {k: v for k, v in params.items() if v is not None}
    return as_list(await client.get(f"/v1/isp-metrics/{metric_type}", params=query))


def _build_sites(sites: object) -> tuple[list[dict] | None, dict | None]:
    if not isinstance(sites, list) or not sites:
        return None, validation_error("sites must be a non-empty list of {hostId, siteId} objects")
    built = []
    for entry in sites:
        if not isinstance(entry, dict) or not entry.get("hostId") or not entry.get("siteId"):
            return None, validation_error("each site needs hostId and siteId (see list_cloud_sites)")
        item = {k: entry[k] for k in _SITE_KEYS if entry.get(k) is not None}
        for key in ("beginTimestamp", "endTimestamp"):
            if key in item and (err := check_timestamp(item[key], key)):
                return None, err
        built.append(item)
    return built, None


async def query_isp_metrics(client: CloudClient, metric_type: str, sites: list[dict]) -> dict:
    """Query ISP metrics for specific sites (read-only POST query). metric_type '5m' or '1h'. sites is a list of {hostId, siteId, beginTimestamp?, endTimestamp?} from list_cloud_sites; timestamps are RFC3339. A status of partialSuccess means some sites were not accessible."""
    if (err := _check_type(metric_type)):
        return err
    built, err = _build_sites(sites)
    if err:
        return err
    response = await client.post(f"/v1/isp-metrics/{metric_type}/query", json={"sites": built})
    data = unwrap(response)
    result = dict(data) if isinstance(data, dict) else {"metrics": data or []}
    if isinstance(response, dict) and response.get("status"):
        result["status"] = response["status"]
    return result


TOOLS = [get_isp_metrics, query_isp_metrics]
