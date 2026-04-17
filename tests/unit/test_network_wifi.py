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
async def test_list_wlans(mock_client):
    from unifi_mcp.tools.network.wifi import list_wlans

    fixture = load_fixture("wlans.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_wlans(mock_client)
    assert len(result) == 3
    assert result[0]["name"] == "HomeWiFi"
    assert result[0]["enabled"] is True


@respx.mock
@pytest.mark.asyncio
async def test_create_wlan_preview(mock_client):
    from unifi_mcp.tools.network.wifi import create_wlan

    result = await create_wlan(
        mock_client,
        name="TestSSID",
        security="wpapsk",
        passphrase="test12345",
        confirm=False,
    )
    assert result["preview"] is True
    assert result["action"] == "create_wlan"


@respx.mock
@pytest.mark.asyncio
async def test_create_wlan_confirmed(mock_client):
    from unifi_mcp.tools.network.wifi import create_wlan

    respx.post("https://192.168.1.1/proxy/network/api/s/default/rest/wlanconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "wlan_new", "name": "TestSSID"}]})
    )
    result = await create_wlan(
        mock_client,
        name="TestSSID",
        security="wpapsk",
        passphrase="test12345",
        confirm=True,
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_wlan_preview(mock_client):
    from unifi_mcp.tools.network.wifi import delete_wlan

    result = await delete_wlan(mock_client, wlan_id="wlan001", confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_toggle_wlan(mock_client):
    from unifi_mcp.tools.network.wifi import toggle_wlan

    respx.put("https://192.168.1.1/proxy/network/api/s/default/rest/wlanconf/wlan003").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "wlan003", "enabled": True}]})
    )
    result = await toggle_wlan(mock_client, wlan_id="wlan003", enabled=True, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_toggle_wlan_preview(mock_client):
    from unifi_mcp.tools.network.wifi import toggle_wlan

    result = await toggle_wlan(mock_client, wlan_id="wlan003", enabled=True, confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_get_wlan_stats(mock_client):
    from unifi_mcp.tools.network.wifi import get_wlan_stats

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_wlan_stats(mock_client)
    assert isinstance(result, dict)
    # Clients fixture has 2 wireless clients on "HomeWiFi"
    assert "HomeWiFi" in result
    assert result["HomeWiFi"]["client_count"] == 2


def test_wifi_tools_list():
    from unifi_mcp.tools.network.wifi import TOOLS
    assert len(TOOLS) == 6
