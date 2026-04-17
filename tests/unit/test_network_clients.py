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
async def test_list_clients(mock_client):
    from unifi_mcp.tools.network.clients import list_clients

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_clients(mock_client)
    assert len(result) == 3
    assert result[0]["hostname"] == "MacBook-Pro"
    assert result[0]["ip"] == "192.168.1.100"
    assert "uptime_human" in result[0]
    assert "tx_human" in result[0]


@respx.mock
@pytest.mark.asyncio
async def test_get_client(mock_client):
    from unifi_mcp.tools.network.clients import get_client

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta/AA:BB:CC:DD:EE:01").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][0]]})
    )
    result = await get_client(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert result["hostname"] == "MacBook-Pro"
    assert result["mac"] == "AA:BB:CC:DD:EE:01"


@respx.mock
@pytest.mark.asyncio
async def test_block_client_preview(mock_client):
    from unifi_mcp.tools.network.clients import block_client

    result = await block_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "block_client"
    assert "confirm=True" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_block_client_confirmed(mock_client):
    from unifi_mcp.tools.network.clients import block_client

    respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await block_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_unblock_client_preview(mock_client):
    from unifi_mcp.tools.network.clients import unblock_client

    result = await unblock_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "unblock_client"


@respx.mock
@pytest.mark.asyncio
async def test_reconnect_client(mock_client):
    from unifi_mcp.tools.network.clients import reconnect_client

    respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await reconnect_client(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert result["action"] == "reconnect_client"


@respx.mock
@pytest.mark.asyncio
async def test_set_client_alias(mock_client):
    from unifi_mcp.tools.network.clients import set_client_alias

    respx.put("https://192.168.1.1/proxy/network/api/s/default/rest/user/cli001").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "cli001", "name": "My Laptop"}]})
    )
    result = await set_client_alias(mock_client, client_id="cli001", name="My Laptop")
    assert result["data"][0]["name"] == "My Laptop"


@respx.mock
@pytest.mark.asyncio
async def test_list_all_clients(mock_client):
    from unifi_mcp.tools.network.clients import list_all_clients

    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/user").mock(
        return_value=httpx.Response(200, json={
            "meta": {"rc": "ok"},
            "data": [
                {"_id": "u1", "mac": "AA:BB:CC:DD:EE:01", "hostname": "MacBook-Pro", "name": "Chris Laptop"},
                {"_id": "u2", "mac": "AA:BB:CC:DD:EE:04", "hostname": "old-device", "name": ""}
            ]
        })
    )
    result = await list_all_clients(mock_client)
    assert len(result) == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_client_history(mock_client):
    from unifi_mcp.tools.network.clients import get_client_history

    respx.post("https://192.168.1.1/proxy/network/api/s/default/stat/report/hourly.user").mock(
        return_value=httpx.Response(200, json={
            "meta": {"rc": "ok"},
            "data": [
                {"time": 1713100000000, "rx_bytes": 1024, "tx_bytes": 2048}
            ]
        })
    )
    result = await get_client_history(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert len(result) == 1
    assert result[0]["rx_bytes"] == 1024


def test_clients_tools_list():
    from unifi_mcp.tools.network.clients import TOOLS
    assert len(TOOLS) == 8
