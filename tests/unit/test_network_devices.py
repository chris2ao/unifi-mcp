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
async def test_list_devices(mock_client):
    from unifi_mcp.tools.network.devices import list_devices

    fixture = load_fixture("devices.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_devices(mock_client)
    assert len(result) == 2
    assert result[0]["name"] == "Office AP"
    assert result[0]["mac"] == "00:11:22:33:44:55"
    assert "uptime_human" in result[0]
    assert "tx_human" in result[0]


@respx.mock
@pytest.mark.asyncio
async def test_get_device(mock_client):
    from unifi_mcp.tools.network.devices import get_device

    fixture = load_fixture("devices.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/00:11:22:33:44:55").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][0]]})
    )
    result = await get_device(mock_client, mac="00:11:22:33:44:55")
    assert result["name"] == "Office AP"


@respx.mock
@pytest.mark.asyncio
async def test_restart_device_preview(mock_client):
    from unifi_mcp.tools.network.devices import restart_device

    result = await restart_device(mock_client, mac="00:11:22:33:44:55", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "restart_device"
    assert result["mac"] == "00:11:22:33:44:55"
    assert "confirm=True" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_restart_device_confirmed(mock_client):
    from unifi_mcp.tools.network.devices import restart_device

    respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await restart_device(mock_client, mac="00:11:22:33:44:55", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_adopt_device_preview(mock_client):
    from unifi_mcp.tools.network.devices import adopt_device

    result = await adopt_device(mock_client, mac="00:11:22:33:44:55", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "adopt_device"


@respx.mock
@pytest.mark.asyncio
async def test_forget_device_preview(mock_client):
    from unifi_mcp.tools.network.devices import forget_device

    result = await forget_device(mock_client, mac="00:11:22:33:44:55", confirm=False)
    assert result["preview"] is True
    assert "forget" in result["action"]


@respx.mock
@pytest.mark.asyncio
async def test_locate_device(mock_client):
    from unifi_mcp.tools.network.devices import locate_device

    respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await locate_device(mock_client, mac="00:11:22:33:44:55", enabled=True)
    assert result["enabled"] is True


@respx.mock
@pytest.mark.asyncio
async def test_rename_device(mock_client):
    from unifi_mcp.tools.network.devices import rename_device

    respx.put("https://192.168.1.1/proxy/network/api/s/default/rest/device/abc123").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "abc123", "name": "New Name"}]})
    )
    result = await rename_device(mock_client, device_id="abc123", name="New Name")
    assert result["data"][0]["name"] == "New Name"


@respx.mock
@pytest.mark.asyncio
async def test_get_device_stats(mock_client):
    from unifi_mcp.tools.network.devices import get_device_stats

    fixture = load_fixture("devices.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/00:11:22:33:44:55").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][0]]})
    )
    result = await get_device_stats(mock_client, mac="00:11:22:33:44:55")
    assert result["mac"] == "00:11:22:33:44:55"
    assert result["cpu_usage"] == "12.5"


@respx.mock
@pytest.mark.asyncio
async def test_get_device_ports(mock_client):
    from unifi_mcp.tools.network.devices import get_device_ports

    fixture = load_fixture("devices.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/66:77:88:99:AA:BB").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][1]]})
    )
    result = await get_device_ports(mock_client, mac="66:77:88:99:AA:BB")
    assert len(result) == 3
    assert result[0]["port"] == 1
    assert result[2]["is_uplink"] is True


@respx.mock
@pytest.mark.asyncio
async def test_get_device_uplinks(mock_client):
    from unifi_mcp.tools.network.devices import get_device_uplinks

    fixture = load_fixture("devices.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/00:11:22:33:44:55").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][0]]})
    )
    result = await get_device_uplinks(mock_client, mac="00:11:22:33:44:55")
    assert result["uplink_mac"] == "66:77:88:99:AA:BB"


def test_devices_tools_list():
    from unifi_mcp.tools.network.devices import TOOLS
    assert len(TOOLS) == 12
