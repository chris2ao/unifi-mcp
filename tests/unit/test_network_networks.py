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
async def test_list_networks(mock_client):
    from unifi_mcp.tools.network.networks import list_networks

    fixture = load_fixture("networks.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_networks(mock_client)
    assert len(result) == 3
    assert result[0]["name"] == "Default"
    assert result[1]["name"] == "IoT"
    assert result[1]["vlan"] == 10


@respx.mock
@pytest.mark.asyncio
async def test_get_network(mock_client):
    from unifi_mcp.tools.network.networks import get_network

    fixture = load_fixture("networks.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/net002").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][1]]})
    )
    result = await get_network(mock_client, network_id="net002")
    assert result["name"] == "IoT"
    assert result["vlan"] == 10


@respx.mock
@pytest.mark.asyncio
async def test_get_network_returns_not_found_for_unknown_id(mock_client):
    from unifi_mcp.tools.network.networks import get_network

    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/missing").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await get_network(mock_client, network_id="missing")
    assert result["error"] is True
    assert result["category"] == "NOT_FOUND"
    assert result["network_id"] == "missing"


@respx.mock
@pytest.mark.asyncio
async def test_create_network_preview(mock_client):
    from unifi_mcp.tools.network.networks import create_network

    result = await create_network(
        mock_client,
        name="TestNet",
        purpose="corporate",
        subnet="192.168.50.0/24",
        vlan=50,
        confirm=False,
    )
    assert result["preview"] is True
    assert result["action"] == "create_network"
    assert result["params"]["name"] == "TestNet"


@respx.mock
@pytest.mark.asyncio
async def test_create_network_confirmed(mock_client):
    from unifi_mcp.tools.network.networks import create_network

    respx.post("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "net_new", "name": "TestNet"}]})
    )
    result = await create_network(
        mock_client,
        name="TestNet",
        purpose="corporate",
        subnet="192.168.50.0/24",
        vlan=50,
        confirm=True,
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_preview(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    result = await delete_network(mock_client, network_id="net002", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "delete_network"


@respx.mock
@pytest.mark.asyncio
async def test_get_dhcp_leases(mock_client):
    from unifi_mcp.tools.network.networks import get_dhcp_leases

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_dhcp_leases(mock_client, network_id="net001")
    assert isinstance(result, list)
    # All 3 fixture clients are on net001
    assert len(result) == 3


def test_networks_tools_list():
    from unifi_mcp.tools.network.networks import TOOLS
    assert len(TOOLS) == 6
