import json
import pytest
import httpx
import respx
from pathlib import Path

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
@pytest.mark.asyncio
async def test_get_system_info(mock_client):
    from unifi_mcp.tools.network.system import get_system_info

    fixture = load_fixture("sysinfo.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sysinfo").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_system_info(mock_client)
    assert result["hostname"] == "UDM-Pro"
    assert result["version"] == "8.6.9"
    assert "uptime_human" in result


@respx.mock
@pytest.mark.asyncio
async def test_get_health(mock_client):
    from unifi_mcp.tools.network.system import get_health

    fixture = load_fixture("health.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/health").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_health(mock_client)
    assert isinstance(result, list)
    assert len(result) == 4
    assert result[0]["subsystem"] == "wan"
    assert result[0]["status"] == "ok"


SYSLOG_ALL = "https://192.168.1.1/proxy/network/v2/api/site/default/system-log/all"
SYSLOG_COUNT = "https://192.168.1.1/proxy/network/v2/api/site/default/system-log/count"
NOW_MS = 1790000000000
HOUR_MS = 3_600_000


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    from unifi_mcp.tools.network import system
    monkeypatch.setattr(system, "_now_ms", lambda: NOW_MS)


def _body(route):
    return json.loads(route.calls.last.request.content)


# --- get_events ---

@respx.mock
@pytest.mark.asyncio
async def test_get_events_posts_system_log_all_with_time_window(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json=load_fixture("system_log_all.json"))
    )
    result = await get_events(mock_client)
    assert route.call_count == 1
    assert _body(route) == {
        "timestampFrom": NOW_MS - 24 * HOUR_MS,
        "timestampTo": NOW_MS,
        "pageNumber": 0,
        "pageSize": 50,
    }
    assert len(result) == 4


@respx.mock
@pytest.mark.asyncio
async def test_get_events_compact_shape_and_rendering(mock_client):
    from unifi_mcp.tools.network.system import get_events

    respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json=load_fixture("system_log_all.json"))
    )
    result = await get_events(mock_client)
    first = result[0]
    assert first["id"] == "000000000000000000000001"
    assert first["time"] == "2026-09-21T14:13:20Z"
    assert first["category"] == "CLIENT_DEVICES"
    assert first["subcategory"] == "MONITORING_WIFI"
    assert first["severity"] == "LOW"
    assert first["key"] == "CLIENT_CONNECTED_WIRELESS_2"
    assert first["event"] == "CLIENT_CONNECTED_WIRELESS"
    assert first["title"] == "WiFi Client Connected"
    assert first["message"] == (
        "Office Laptop connected to Example WiFi on Office AP. Connection Info: "
        "Ch. 37 (6 GHz, 160 MHz), -60 dBm. IP: 192.0.2.50"
    )
    assert first["target"] == {
        "type": "CLIENT", "id": "aa:bb:cc:00:00:01",
        "name": "Office Laptop", "ip": "192.0.2.50",
    }
    assert "parameters" not in first
    assert "message_raw" not in first


@respx.mock
@pytest.mark.asyncio
async def test_get_events_render_brackets_title_and_site_target(mock_client):
    from unifi_mcp.tools.network.system import get_events

    respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json=load_fixture("system_log_all.json"))
    )
    failover = (await get_events(mock_client))[2]
    assert failover["title"] == "WAN2 Internet Failover Active"
    assert failover["message"] == (
        "Internet connection WAN1 on port 9 is down and WAN2 (Example ISP) is now active."
    )
    assert failover["target"] == {"type": "SITE"}


@respx.mock
@pytest.mark.asyncio
async def test_get_events_unknown_placeholder_left_intact(mock_client):
    from unifi_mcp.tools.network.system import get_events

    respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json=load_fixture("system_log_all.json"))
    )
    audit = (await get_events(mock_client))[3]
    assert audit["message"] == (
        "Example Admin accessed the Network application from {UNKNOWN_PARAM}."
    )
    assert audit["target"]["type"] == "ADMIN"
    assert audit["target"]["name"] == "Example Admin"


@respx.mock
@pytest.mark.asyncio
async def test_get_events_filters_are_normalized_and_sent(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await get_events(
        mock_client, limit=10, hours=2, page=3,
        categories=["security", "VPN", "security"], severities=["very_high"],
    )
    assert _body(route) == {
        "timestampFrom": NOW_MS - 2 * HOUR_MS,
        "timestampTo": NOW_MS,
        "pageNumber": 3,
        "pageSize": 10,
        "categories": ["SECURITY", "VPN"],
        "severities": ["VERY_HIGH"],
    }


@respx.mock
@pytest.mark.asyncio
async def test_get_events_accepts_single_string_filters(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await get_events(mock_client, categories="AUDIT", severities="MEDIUM")
    body = _body(route)
    assert body["categories"] == ["AUDIT"]
    assert body["severities"] == ["MEDIUM"]


@respx.mock
@pytest.mark.asyncio
async def test_get_events_empty_filter_lists_are_omitted(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await get_events(mock_client, categories=[], severities=[])
    body = _body(route)
    assert "categories" not in body
    assert "severities" not in body


@respx.mock
@pytest.mark.asyncio
async def test_get_events_legacy_threats_category(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await get_events(mock_client, category="threats")
    assert result == []
    assert _body(route)["categories"] == ["SECURITY"]


@respx.mock
@pytest.mark.asyncio
async def test_get_events_legacy_triggers_means_all(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await get_events(mock_client, category="triggers")
    assert "categories" not in _body(route)


@respx.mock
@pytest.mark.asyncio
async def test_get_events_explicit_categories_win_over_legacy(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await get_events(mock_client, category="threats", categories=["VPN"])
    assert _body(route)["categories"] == ["VPN"]


@respx.mock
@pytest.mark.asyncio
async def test_get_events_bare_list_and_truncation(mock_client):
    from unifi_mcp.tools.network.system import get_events

    events = load_fixture("system_log_all.json")["data"]
    respx.post(SYSLOG_ALL).mock(return_value=httpx.Response(200, json=events))
    result = await get_events(mock_client, limit=2)
    assert [e["id"] for e in result] == [
        "000000000000000000000001", "000000000000000000000002",
    ]


@respx.mock
@pytest.mark.asyncio
async def test_get_events_tolerates_sparse_events(mock_client):
    from unifi_mcp.tools.network.system import get_events

    respx.post(SYSLOG_ALL).mock(return_value=httpx.Response(200, json={"data": [
        {"id": "x1"},
        {"id": "x2", "timestamp": "bogus", "parameters": "bogus", "target": "CLIENT",
         "message_raw": "{CLIENT} left"},
        "not-a-dict",
        {"id": "x3", "timestamp": 10**18, "target": ["X"], "parameters": {}},
    ]}))
    result = await get_events(mock_client)
    assert len(result) == 3
    assert result[2]["time"] is None and result[2]["target"] is None
    assert result[0]["time"] is None
    assert result[0]["message"] is None
    assert result[0]["target"] is None
    assert result[1]["message"] == "{CLIENT} left"
    assert result[1]["target"] == {"type": "CLIENT"}


@respx.mock
@pytest.mark.asyncio
async def test_get_events_unexpected_payload_returns_error(mock_client):
    from unifi_mcp.tools.network.system import get_events

    respx.post(SYSLOG_ALL).mock(return_value=httpx.Response(200, json={"data": None}))
    result = await get_events(mock_client)
    assert result[0]["error"] is True
    assert result[0]["category"] == "UNEXPECTED_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,needle", [
    ({"category": "bogus"}, "category"),
    ({"categories": ["NOPE"]}, "categories"),
    ({"categories": [1]}, "categories"),
    ({"severities": ["CRITICAL"]}, "severities"),
    ({"limit": 0}, "limit"),
    ({"limit": 1001}, "limit"),
    ({"limit": 2.5}, "limit"),
    ({"limit": True}, "limit"),
    ({"hours": 0}, "hours"),
    ({"hours": 2161}, "hours"),
    ({"page": -1}, "page"),
    ({"page": 1.5}, "page"),
])
async def test_get_events_validation_errors(mock_client, kwargs, needle):
    from unifi_mcp.tools.network.system import get_events

    with respx.mock(assert_all_called=False) as router:
        result = await get_events(mock_client, **kwargs)
        assert router.calls.call_count == 0
    assert isinstance(result, list) and len(result) == 1
    assert result[0]["error"] is True
    assert result[0]["category"] == "VALIDATION_ERROR"
    assert needle in result[0]["message"]


def test_event_enum_constants_match_live_console():
    from unifi_mcp.tools.network.system import (
        ALARM_SEVERITIES, SYSTEM_LOG_CATEGORIES, SYSTEM_LOG_SEVERITIES,
    )
    assert set(SYSTEM_LOG_CATEGORIES) == {
        "SECURITY", "UNIFI_DEVICES", "SOFTWARE_UPDATES", "VPN", "POWER",
        "UNIFI_ETHERNET_PORTS", "CLIENT_DEVICES", "UNKNOWN", "AUDIT",
        "INTERNET_AND_WAN",
    }
    assert set(SYSTEM_LOG_SEVERITIES) == {
        "HIGH", "LOW", "MEDIUM", "VERY_HIGH", "WARNING", "INFO",
    }
    assert ALARM_SEVERITIES == ("HIGH", "VERY_HIGH")


# --- get_alarms ---

@respx.mock
@pytest.mark.asyncio
async def test_get_alarms_queries_high_severities(mock_client):
    from unifi_mcp.tools.network.system import get_alarms

    events = load_fixture("system_log_all.json")["data"][1:3]
    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": events})
    )
    result = await get_alarms(mock_client)
    assert _body(route) == {
        "timestampFrom": NOW_MS - 168 * HOUR_MS,
        "timestampTo": NOW_MS,
        "pageNumber": 0,
        "pageSize": 50,
        "severities": ["HIGH", "VERY_HIGH"],
    }
    assert [a["severity"] for a in result] == ["VERY_HIGH", "HIGH"]
    assert result[0]["event"] == "THREAT_BLOCKED"


@respx.mock
@pytest.mark.asyncio
async def test_get_alarms_custom_window_and_empty(mock_client):
    from unifi_mcp.tools.network.system import get_alarms

    route = respx.post(SYSLOG_ALL).mock(
        return_value=httpx.Response(200, json={"data": [], "total_element_count": 0})
    )
    result = await get_alarms(mock_client, hours=12, limit=5)
    assert result == []
    body = _body(route)
    assert body["timestampFrom"] == NOW_MS - 12 * HOUR_MS
    assert body["pageSize"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"hours": 0}, {"limit": 0}, {"limit": "5"}])
async def test_get_alarms_validation(mock_client, kwargs):
    from unifi_mcp.tools.network.system import get_alarms

    result = await get_alarms(mock_client, **kwargs)
    assert result[0]["category"] == "VALIDATION_ERROR"


# --- get_event_counts ---

@respx.mock
@pytest.mark.asyncio
async def test_get_event_counts(mock_client):
    from unifi_mcp.tools.network.system import get_event_counts

    route = respx.post(SYSLOG_COUNT).mock(
        return_value=httpx.Response(200, json=load_fixture("system_log_count.json"))
    )
    result = await get_event_counts(mock_client)
    assert _body(route) == {"timestampFrom": NOW_MS - 24 * HOUR_MS, "timestampTo": NOW_MS}
    assert result["hours"] == 24
    assert result["time_to"] == "2026-09-21T14:13:20Z"
    assert result["time_from"] == "2026-09-20T14:13:20Z"
    assert result["total"] == 4749
    assert list(result["by_category"].items())[0] == ("CLIENT_DEVICES", 3977)
    assert result["by_category"]["SECURITY"] == 748
    assert list(result["by_event"])[0] == "CLIENT_DISCONNECTED_WIRELESS"
    assert result["by_event"]["THREAT_BLOCKED"] == 748
    assert result["by_type"] == {"GENERAL": 4729, "AUDIT": 20}


@respx.mock
@pytest.mark.asyncio
async def test_get_event_counts_with_filters(mock_client):
    from unifi_mcp.tools.network.system import get_event_counts

    route = respx.post(SYSLOG_COUNT).mock(
        return_value=httpx.Response(200, json={"categories": [], "events": [], "type": []})
    )
    result = await get_event_counts(
        mock_client, hours=168, categories=["security"], severities=["HIGH", "VERY_HIGH"],
    )
    body = _body(route)
    assert body["timestampFrom"] == NOW_MS - 168 * HOUR_MS
    assert body["categories"] == ["SECURITY"]
    assert body["severities"] == ["HIGH", "VERY_HIGH"]
    assert result["total"] == 0
    assert result["by_category"] == {}


@respx.mock
@pytest.mark.asyncio
async def test_get_event_counts_tolerates_odd_shapes(mock_client):
    from unifi_mcp.tools.network.system import get_event_counts

    respx.post(SYSLOG_COUNT).mock(return_value=httpx.Response(200, json={
        "categories": [{"name": "VPN", "count": 2}, {"name": None, "count": 1}, "x",
                       {"name": "AUDIT", "count": "bad"}],
    }))
    result = await get_event_counts(mock_client)
    assert result["by_category"] == {"VPN": 2}
    assert result["total"] == 2
    assert result["by_event"] == {}
    assert result["by_type"] == {}


@respx.mock
@pytest.mark.asyncio
async def test_get_event_counts_non_dict_response(mock_client):
    from unifi_mcp.tools.network.system import get_event_counts

    respx.post(SYSLOG_COUNT).mock(return_value=httpx.Response(200, json=[]))
    result = await get_event_counts(mock_client)
    assert result["error"] is True
    assert result["category"] == "UNEXPECTED_RESPONSE"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"hours": 0}, {"hours": "24"}, {"categories": ["BAD"]}, {"severities": ["BAD"]},
])
async def test_get_event_counts_validation(mock_client, kwargs):
    from unifi_mcp.tools.network.system import get_event_counts

    result = await get_event_counts(mock_client, **kwargs)
    assert result["error"] is True
    assert result["category"] == "VALIDATION_ERROR"


def test_system_tools_list():
    from unifi_mcp.tools.network.system import TIER2_TOOLS, TOOLS
    names = [t.__name__ for t in TOOLS]
    assert names == [
        "get_system_info", "get_health", "get_alarms", "get_events", "get_event_counts",
    ]
    assert TIER2_TOOLS == {}
