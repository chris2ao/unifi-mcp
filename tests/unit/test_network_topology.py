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
async def test_get_topology(mock_client):
    from unifi_mcp.tools.network.topology import get_topology

    fixture = load_fixture("topology.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_topology(mock_client)
    assert isinstance(result, dict)
    assert "nodes" in result
    assert "edges" in result
    assert len(result["nodes"]) == 3


@respx.mock
@pytest.mark.asyncio
async def test_get_uplink_tree(mock_client):
    from unifi_mcp.tools.network.topology import get_uplink_tree

    fixture = load_fixture("topology.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_uplink_tree(mock_client)
    assert isinstance(result, dict)
    # Root gateway has no uplink
    assert result["mac"] == "CC:DD:EE:FF:00:11"
    assert len(result["children"]) > 0


@respx.mock
@pytest.mark.asyncio
async def test_get_port_table(mock_client):
    from unifi_mcp.tools.network.topology import get_port_table

    fixture = load_fixture("topology.json")
    # The switch is at index 1
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/66:77:88:99:AA:BB").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][1]]})
    )
    result = await get_port_table(mock_client, mac="66:77:88:99:AA:BB")
    assert isinstance(result, list)
    assert len(result) == 2


def test_topology_tools_list():
    from unifi_mcp.tools.network.topology import TOOLS
    assert len(TOOLS) == 3
