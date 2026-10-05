import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.network import traffic_flows as tf

FIXTURES = Path(__file__).parent.parent / "fixtures"
URL = "https://192.0.2.1/proxy/network/v2/api/site/default/traffic-flows"
NOW = 1_700_000_100_000


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.0.2.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    monkeypatch.setattr(tf, "_now_ms", lambda: NOW)
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def fixture() -> dict:
    return json.loads((FIXTURES / "traffic_flows.json").read_text())


def body_of(route, call=0) -> dict:
    return json.loads(route.calls[call].request.content)


def test_module_declarations():
    assert tf.GROUP == "insights"
    assert tf.TIER2_TOOLS == {}
    assert len(tf.TOOLS) == 6
    assert {t.__name__ for t in tf.TOOLS} >= {"get_blocked_flows", "get_flow_summary"}


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_flows_compact_and_body(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.list_traffic_flows(mock_client, minutes=30, limit=3)
    body = body_of(route)
    assert body == {
        "timestampFrom": NOW - 30 * 60_000, "timestampTo": NOW,
        "pageNumber": 0, "pageSize": 3,
    }
    assert result["returned"] == 3
    assert result["total_matching"] == 6
    first = result["flows"][0]
    assert first["time"] > result["flows"][1]["time"]
    assert first["source"]["name"] == "Laptop"
    assert first["destination"]["domains"] == ["www.example.com"]
    assert first["bytes_total"] == 905000
    assert first["network_in"] == "Main LAN"
    assert "traffic_data" not in first


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_flows_filters_sent(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    await tf.list_traffic_flows(
        mock_client, direction="OUTGOING", protocol="udp", action="Blocked", risk="low", search=" dns "
    )
    body = body_of(route)
    assert body["direction"] == ["outgoing"]
    assert body["protocol"] == ["UDP"]
    assert body["action"] == ["blocked"]
    assert body["risk"] == ["low"]
    assert body["search_text"] == "dns"


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_flows_empty(mock_client):
    respx.post(URL).mock(return_value=httpx.Response(
        200, json={"data": [], "total_element_count": 0, "has_next": False}))
    result = await tf.list_traffic_flows(mock_client)
    assert result["flows"] == []
    assert "No flows" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_flows_total_cap_note(mock_client):
    payload = {**fixture(), "total_element_count": 10000, "has_next": True}
    respx.post(URL).mock(return_value=httpx.Response(200, json=payload))
    result = await tf.list_traffic_flows(mock_client, limit=2)
    assert "10,000" in result["note"]


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_flows_bare_list_shape(mock_client):
    respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()["data"]))
    result = await tf.list_traffic_flows(mock_client)
    assert result["returned"] == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"minutes": 0}, {"minutes": 10081}, {"minutes": "60"}, {"minutes": True},
    {"limit": 0}, {"limit": 501},
    {"direction": "sideways"}, {"action": "maybe"}, {"risk": "critical"},
    {"protocol": "TCP;DROP"}, {"protocol": ""}, {"search": "   "}, {"search": "x" * 101},
])
async def test_list_traffic_flows_validation(mock_client, kwargs):
    result = await tf.list_traffic_flows(mock_client, **kwargs)
    assert result["error"] is True
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_pagination_pages_and_cap(mock_client):
    page = lambda n: {"data": [{"id": f"{n}-{i}", "flow_start_time": i} for i in range(500)],
                      "total_element_count": 10000, "has_next": True}
    route = respx.post(URL).mock(side_effect=[
        httpx.Response(200, json=page(0)), httpx.Response(200, json=page(1)),
    ])
    flows, total, truncated = await tf._scan(mock_client, 60, {}, 700)
    assert len(flows) == 700
    assert truncated is True
    assert total == 10000
    assert [body_of(route, i)["pageNumber"] for i in range(2)] == [0, 1]
    assert [body_of(route, i)["pageSize"] for i in range(2)] == [500, 200]


@respx.mock
@pytest.mark.asyncio
async def test_scan_stops_when_no_next(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    flows, total, truncated = await tf._scan(mock_client, 60, {}, 2000)
    assert (len(flows), total, truncated) == (6, 6, False)
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_top_talkers_by_source(mock_client):
    respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.get_top_talkers(mock_client, limit=2)
    assert result["by"] == "source"
    assert result["flows_scanned"] == 6
    assert result["truncated"] is False
    top = result["top"]
    assert len(top) == 2
    assert top[0]["key"] == "10.0.0.11"
    assert top[0]["name"] == "Laptop"
    assert top[0]["bytes_total"] == 905000 + 300
    assert top[0]["flows"] == 2


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("by,first", [
    ("destination", "203.0.113.10"), ("service", "HTTPS"), ("domain", "www.example.com"),
])
async def test_top_talkers_groupings(mock_client, by, first):
    respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.get_top_talkers(mock_client, by=by)
    assert result["top"][0]["key"] == first


@respx.mock
@pytest.mark.asyncio
async def test_top_talkers_service_defaults_other(mock_client):
    respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.get_top_talkers(mock_client, by="service", limit=100)
    assert "OTHER" in {r["key"] for r in result["top"]}


@respx.mock
@pytest.mark.asyncio
async def test_top_talkers_empty(mock_client):
    respx.post(URL).mock(return_value=httpx.Response(200, json={"data": [], "has_next": False}))
    result = await tf.get_top_talkers(mock_client)
    assert result["top"] == []
    assert "No flows" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"by": "app"}, {"limit": 0}, {"limit": 101}, {"max_flows": 99}, {"max_flows": 5001}, {"minutes": 0},
])
async def test_top_talkers_validation(mock_client, kwargs):
    result = await tf.get_top_talkers(mock_client, **kwargs)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_filter_flows_by_app(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.filter_flows_by_app(mock_client, "google", minutes=120, limit=5)
    assert body_of(route)["search_text"] == "google"
    assert result["app_name"] == "google"
    assert result["window_minutes"] == 120


@pytest.mark.asyncio
async def test_filter_flows_by_app_validation(mock_client):
    assert (await tf.filter_flows_by_app(mock_client, ""))["category"] == "VALIDATION_ERROR"
    assert (await tf.filter_flows_by_app(mock_client, "x", limit=0))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_filter_flows_by_client_ip_queries_both_sides(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.filter_flows_by_client(mock_client, client_ip="10.0.0.11")
    assert route.call_count == 2
    assert body_of(route, 0)["source_ip"] == ["10.0.0.11"]
    assert body_of(route, 1)["destination_ip"] == ["10.0.0.11"]
    # same ids returned by both queries are deduplicated
    assert result["returned"] == 6
    assert result["client"]["client_ip"] == "10.0.0.11"


@respx.mock
@pytest.mark.asyncio
async def test_filter_flows_by_client_mac_normalized(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    await tf.filter_flows_by_client(mock_client, client_mac="AA-BB-CC-00-00-01")
    assert body_of(route, 0)["source_mac"] == ["aa:bb:cc:00:00:01"]
    assert body_of(route, 1)["destination_mac"] == ["aa:bb:cc:00:00:01"]


@respx.mock
@pytest.mark.asyncio
async def test_filter_flows_by_client_ip_and_mac(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    await tf.filter_flows_by_client(mock_client, client_ip="10.0.0.11", client_mac="aabbcc000001")
    body = body_of(route, 0)
    assert body["source_ip"] == ["10.0.0.11"] and body["source_mac"] == ["aa:bb:cc:00:00:01"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {}, {"client_ip": "not-an-ip"}, {"client_mac": "zz"}, {"client_ip": "10.0.0.1", "limit": 0},
])
async def test_filter_flows_by_client_validation(mock_client, kwargs):
    result = await tf.filter_flows_by_client(mock_client, **kwargs)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_get_blocked_flows(mock_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.get_blocked_flows(mock_client, minutes=15, limit=10)
    assert body_of(route)["action"] == ["blocked"]
    assert result["window_minutes"] == 15


@pytest.mark.asyncio
async def test_get_blocked_flows_validation(mock_client):
    assert (await tf.get_blocked_flows(mock_client, minutes=-1))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_get_flow_summary(mock_client):
    respx.post(URL).mock(return_value=httpx.Response(200, json=fixture()))
    result = await tf.get_flow_summary(mock_client)
    assert result["flows_scanned"] == 6
    assert result["by_action"] == {"allowed": 5, "blocked": 1}
    assert result["by_risk"] == {"low": 5, "medium": 1}
    assert result["by_direction"] == {"outgoing": 4, "incoming": 1, "local": 1}
    assert result["by_protocol"] == {"TCP": 4, "UDP": 2}
    assert result["top_services"][0] == {"service": "HTTPS", "flows": 3}
    assert result["bytes_total"] > 1_000_000


@pytest.mark.asyncio
async def test_get_flow_summary_validation(mock_client):
    assert (await tf.get_flow_summary(mock_client, minutes=99999))["category"] == "VALIDATION_ERROR"


def test_compact_flow_handles_sparse_flow():
    out = tf._compact_flow({"action": "allowed"})
    assert out["bytes_total"] == 0
    assert out["policies"] == []
    assert out["destination"]["domains"] == []
    assert "network_in" not in out


def test_compact_flow_network_out():
    out = tf._compact_flow({"out": {"network_name": "Guest"}})
    assert out["network_out"] == "Guest"
