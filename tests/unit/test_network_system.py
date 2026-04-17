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


@respx.mock
@pytest.mark.asyncio
async def test_get_alarms(mock_client):
    from unifi_mcp.tools.network.system import get_alarms

    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/alarm").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await get_alarms(mock_client)
    assert isinstance(result, list)
    assert len(result) == 0


@respx.mock
@pytest.mark.asyncio
async def test_get_events_uses_system_log_triggers(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(
        "https://192.168.1.1/proxy/network/v2/api/site/default/system-log/triggers"
    ).mock(
        return_value=httpx.Response(200, json={
            "data": [{"key": "EVT_AP_Connected", "msg": "AP connected", "time": 1713100000000}],
            "page_number": 0,
            "total_element_count": 1,
        })
    )
    result = await get_events(mock_client)
    assert route.called
    assert result[0]["key"] == "EVT_AP_Connected"


@respx.mock
@pytest.mark.asyncio
async def test_get_events_threats_category(mock_client):
    from unifi_mcp.tools.network.system import get_events

    route = respx.post(
        "https://192.168.1.1/proxy/network/v2/api/site/default/system-log/threats"
    ).mock(return_value=httpx.Response(200, json={"data": []}))
    result = await get_events(mock_client, category="threats")
    assert route.called
    assert result == []


@pytest.mark.asyncio
async def test_get_events_rejects_invalid_category(mock_client):
    from unifi_mcp.tools.network.system import get_events

    result = await get_events(mock_client, category="bogus")
    assert result[0]["error"] is True
    assert result[0]["category"] == "VALIDATION_ERROR"


def test_system_tools_list():
    from unifi_mcp.tools.network.system import TOOLS
    assert len(TOOLS) == 4
    names = [t.__name__ for t in TOOLS]
    assert "get_system_info" in names
    assert "get_health" in names
    assert "get_alarms" in names
    assert "get_events" in names
