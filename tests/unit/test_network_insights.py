import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.errors import UnifiError
from unifi_mcp.tools.network import insights

FIXTURES = Path(__file__).parent.parent / "fixtures"
BASE = "https://192.0.2.1"
SITE_UUID = "00000000-0000-0000-0000-0000000000a1"
DASH = f"{BASE}/proxy/network/v2/api/site/default/aggregated-dashboard"
SPEED = f"{BASE}/proxy/network/v2/api/site/default/speedtest"
LB = f"{BASE}/proxy/network/v2/api/site/default/wan/load-balancing/status"
SITES = f"{BASE}/proxy/network/integration/v1/sites"
WANS = f"{BASE}/proxy/network/integration/v1/sites/{SITE_UUID}/wans"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


def mock_sites():
    respx.get(SITES).mock(return_value=httpx.Response(
        200, json={"data": [{"id": SITE_UUID, "internalReference": "default"}]}))


def test_module_declarations():
    assert insights.GROUP == "insights"
    assert insights.TIER2_TOOLS == {}
    assert [t.__name__ for t in insights.TOOLS] == [
        "get_dashboard_summary", "get_speedtest_history", "get_wan_status"]


@respx.mock
@pytest.mark.asyncio
async def test_dashboard_summary(mock_client):
    respx.get(DASH).mock(return_value=httpx.Response(200, json=load("insights_dashboard.json")))
    r = await insights.get_dashboard_summary(mock_client)
    assert r["period_start"] == "2023-11-14T22:13:20Z"
    assert r["wifi_doctor"]["pending_actions"] == ["OPTIMIZE_IOT_CONNECTIVITY"]
    assert r["wifi_doctor"]["completed_actions"] == ["UPDATE_DEVICE_FIRMWARE", "INTER_ROAMING_ENHANCEMENT"]
    assert r["isp_metrics"] == {"available": False, "reason": "no_data"}
    assert r["cybersecure"]["threats"] == 12
    assert r["most_active_clients"][0]["name"] == "Laptop"
    assert r["most_active_clients"][0]["bytes_total"] == 4000000
    assert r["most_active_aps"][0] == {
        "name": "Office AP", "model": "U7PRO", "mac": "aa:bb:cc:00:01:01",
        "bytes_total": 800000, "satisfaction": 99}
    assert r["top_apps"][0]["application_id"] == 185
    assert r["traffic_bytes"] == {"rx": 9000, "tx": 1000}
    wan = r["wan_activity"][0]
    assert wan["wan"] == "WAN" and wan["isp"] == "Example ISP"
    assert wan["avg_latency_ms"] == 6.0 and wan["max_latency_ms"] == 12.0
    assert wan["avg_packet_loss_pct"] == 0.5 and wan["peak_rx_bps"] == 11000000.0
    assert r["upgradable_device_count"] == 2
    assert r["wifi_connectivity"][1] == {
        "radio": "ng", "success_ratio": 92.5, "failed_connections": 3, "total_attempts": 40}
    net = r["internet"]
    assert net["downtime_events"] == 2 and net["downtime_seconds_total"] == 150
    assert net["recent_downtime"][0]["seconds"] == 30
    assert net["samples_with_downtime"] == 1 and net["samples_with_high_latency"] == 1
    assert net["service_latency_ms"]["WAN"]["google"] == 16
    assert net["latest_speedtest"]["download_mbps"] == 900
    assert net["speedtest_schedule"] == "0 5 * * *"
    assert len(json.dumps(r)) < 6000


@respx.mock
@pytest.mark.asyncio
async def test_dashboard_sparse_payload(mock_client):
    respx.get(DASH).mock(return_value=httpx.Response(200, json={
        "isp_metrics": {"avg_latency": 12, "series": [1, 2]}, "wifi_doctor": None,
        "wan_activity": {"activity_by_network_group": {"WAN": {}}}}))
    r = await insights.get_dashboard_summary(mock_client)
    assert r["isp_metrics"] == {"available": True, "avg_latency": 12}
    assert r["wifi_doctor"]["pending_actions"] == []
    assert r["most_active_clients"] == []
    assert r["upgradable_device_count"] == 0
    assert r["wan_activity"][0]["avg_latency_ms"] is None
    assert r["internet"]["latest_speedtest"] is None
    assert r["period_start"] is None


@respx.mock
@pytest.mark.asyncio
async def test_dashboard_empty_response(mock_client):
    respx.get(DASH).mock(return_value=httpx.Response(200, json={}))
    r = await insights.get_dashboard_summary(mock_client)
    assert r["error"] is True and r["category"] == "UNEXPECTED_RESPONSE"


@respx.mock
@pytest.mark.asyncio
async def test_speedtest_history_newest_first(mock_client):
    respx.get(SPEED).mock(return_value=httpx.Response(200, json=load("insights_speedtest.json")))
    r = await insights.get_speedtest_history(mock_client, limit=3)
    assert r["total_matching"] == 4 and r["returned"] == 3
    assert [x["id"] for x in r["results"]] == ["st3", "st2", "st1"]
    assert r["results"][0]["time"] == "2023-11-17T22:13:20Z"
    assert r["summary"]["failed_or_zero"] == 0
    assert r["summary"]["max_download_mbps"] == 1900


@respx.mock
@pytest.mark.asyncio
async def test_speedtest_history_wan_filter_and_zero(mock_client):
    respx.get(SPEED).mock(return_value=httpx.Response(200, json=load("insights_speedtest.json")))
    r = await insights.get_speedtest_history(mock_client, wan="wan")
    assert [x["id"] for x in r["results"]] == ["st1", "st0"]
    assert r["summary"]["failed_or_zero"] == 1
    assert r["summary"]["avg_download_mbps"] == 900


@respx.mock
@pytest.mark.asyncio
async def test_speedtest_history_since_days_sends_timestamp(mock_client, monkeypatch):
    monkeypatch.setattr(insights.time, "time", lambda: 1_700_000_000)
    route = respx.get(SPEED).mock(return_value=httpx.Response(200, json={"data": []}))
    r = await insights.get_speedtest_history(mock_client, since_days=2)
    assert route.calls[0].request.url.params["timestampFrom"] == str(1_700_000_000_000 - 2 * 86_400_000)
    assert r["results"] == [] and "No speed test" in r["message"]


@respx.mock
@pytest.mark.asyncio
async def test_speedtest_bare_list_shape(mock_client):
    respx.get(SPEED).mock(return_value=httpx.Response(200, json=load("insights_speedtest.json")["data"]))
    assert (await insights.get_speedtest_history(mock_client))["total_matching"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"limit": 0}, {"limit": 201}, {"limit": "5"}, {"limit": True},
    {"wan": "WAN/../x"}, {"wan": 5}, {"since_days": 0}, {"since_days": 4000}, {"since_days": 1.5},
])
async def test_speedtest_validation(mock_client, kwargs):
    r = await insights.get_speedtest_history(mock_client, **kwargs)
    assert r["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_wan_status_joins_names(mock_client):
    mock_sites()
    respx.get(LB).mock(return_value=httpx.Response(200, json=load("insights_wan_lb.json")))
    respx.get(WANS).mock(return_value=httpx.Response(200, json=load("insights_wans.json")))
    r = await insights.get_wan_status(mock_client)
    assert r["active_wans"] == ["Internet 1"] and r["standby_wans"] == ["Internet 2"]
    assert r["other_state_wans"] == []
    assert r["wans"][0] == {
        "name": "Internet 1", "wan": "WAN", "state": "ACTIVE",
        "wan_id": "00000000-0000-0000-0000-0000000000d1"}
    assert "warning" not in r


@respx.mock
@pytest.mark.asyncio
async def test_wan_status_survives_wans_failure(mock_client):
    mock_sites()
    respx.get(LB).mock(return_value=httpx.Response(200, json=load("insights_wan_lb.json")))
    respx.get(WANS).mock(return_value=httpx.Response(500))
    r = await insights.get_wan_status(mock_client)
    assert r["wans"][0]["wan_id"] == ""
    assert "WAN names unavailable" in r["warning"]


@respx.mock
@pytest.mark.asyncio
async def test_wan_status_empty_and_other_states(mock_client):
    mock_sites()
    respx.get(WANS).mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(LB).mock(return_value=httpx.Response(200, json={"wan_interfaces": []}))
    assert "No WAN" in (await insights.get_wan_status(mock_client))["message"]
    respx.get(LB).mock(return_value=httpx.Response(200, json={"wan_interfaces": [
        {"name": "Internet 1", "state": "DOWN", "wan_networkgroup": "WAN"}]}))
    assert (await insights.get_wan_status(mock_client))["other_state_wans"] == ["Internet 1"]


@respx.mock
@pytest.mark.asyncio
async def test_wan_status_primary_error_propagates(mock_client):
    respx.get(LB).mock(return_value=httpx.Response(404))
    with pytest.raises(UnifiError):
        await insights.get_wan_status(mock_client)


def test_summarize_dashboard_skips_unexpected_shapes():
    from unifi_mcp.tools.network.insights import summarize_dashboard

    data = {
        "wan_activity": {"activity_by_network_group": [], "network_groups": []},
        "most_active_clients": {"usage_by_client": {"a": 1}},
        "most_active_aps": {"usage_by_ap": "x"},
        "traffic_identification": {"usage_by_app": {"a": 1}},
        "wifi_connectivity": {"radio_connectivity": {"a": 1}},
    }
    result = summarize_dashboard(data)
    assert result["most_active_clients"] == [] and result["most_active_aps"] == []
    assert result["top_apps"] == []
