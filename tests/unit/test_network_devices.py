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
async def test_forget_device_online_uses_devmgr(mock_client):
    """Online devices route to /cmd/devmgr so the controller can send unadopt."""
    from unifi_mcp.tools.network.devices import forget_device

    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/aa:bb:cc:dd:ee:01").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:01", "state": 1}]})
    )
    devmgr_route = respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:01"}]})
    )
    result = await forget_device(mock_client, mac="aa:bb:cc:dd:ee:01", confirm=True)
    assert result["executed"] is True
    assert result["device_state"] == "online"
    assert result["endpoint"].endswith("/cmd/devmgr")
    assert result["retried_on_sitemgr"] is False
    assert devmgr_route.called
    posted = json.loads(devmgr_route.calls.last.request.content)
    assert posted == {"cmd": "delete-device", "mac": "aa:bb:cc:dd:ee:01"}


@respx.mock
@pytest.mark.asyncio
async def test_forget_device_offline_uses_sitemgr(mock_client):
    """Offline devices route directly to /cmd/sitemgr (controller-side purge)."""
    from unifi_mcp.tools.network.devices import forget_device

    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/aa:bb:cc:dd:ee:02").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:02", "state": 0}]})
    )
    devmgr_route = respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    sitemgr_route = respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/sitemgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:02"}]})
    )
    result = await forget_device(mock_client, mac="aa:bb:cc:dd:ee:02", confirm=True)
    assert result["device_state"] == "offline"
    assert result["endpoint"].endswith("/cmd/sitemgr")
    assert result["retried_on_sitemgr"] is False
    assert sitemgr_route.called
    assert not devmgr_route.called  # offline path bypasses devmgr entirely


@respx.mock
@pytest.mark.asyncio
async def test_forget_device_devmgr_silent_noop_retries_on_sitemgr(mock_client):
    """When devmgr returns rc=ok with empty data, retry on sitemgr."""
    from unifi_mcp.tools.network.devices import forget_device

    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/aa:bb:cc:dd:ee:03").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:03", "state": 1}]})
    )
    devmgr_route = respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    sitemgr_route = respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/sitemgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:03"}]})
    )
    result = await forget_device(mock_client, mac="aa:bb:cc:dd:ee:03", confirm=True)
    assert result["retried_on_sitemgr"] is True
    assert result["endpoint"].endswith("/cmd/sitemgr")
    assert devmgr_route.called
    assert sitemgr_route.called


@respx.mock
@pytest.mark.asyncio
async def test_forget_device_state_unknown_defaults_to_sitemgr(mock_client):
    """If the state probe fails (device gone from stat/device), default to sitemgr."""
    from unifi_mcp.tools.network.devices import forget_device

    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/aa:bb:cc:dd:ee:04").mock(
        return_value=httpx.Response(404, json={"meta": {"rc": "error", "msg": "api.err.NotFound"}, "data": []})
    )
    sitemgr_route = respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/sitemgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "x", "mac": "aa:bb:cc:dd:ee:04"}]})
    )
    result = await forget_device(mock_client, mac="aa:bb:cc:dd:ee:04", confirm=True)
    assert result["device_state"] == "unknown"
    assert result["endpoint"].endswith("/cmd/sitemgr")
    assert sitemgr_route.called


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
