import pytest

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


def _assert_unavailable(result):
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["error"] is True
    assert result[0]["category"] == "PRODUCT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_list_traffic_flows_returns_unavailable(mock_client):
    from unifi_mcp.tools.network.traffic_flows import list_traffic_flows
    _assert_unavailable(await list_traffic_flows(mock_client))


@pytest.mark.asyncio
async def test_get_top_talkers_returns_unavailable(mock_client):
    from unifi_mcp.tools.network.traffic_flows import get_top_talkers
    _assert_unavailable(await get_top_talkers(mock_client))


@pytest.mark.asyncio
async def test_filter_flows_by_app_returns_unavailable(mock_client):
    from unifi_mcp.tools.network.traffic_flows import filter_flows_by_app
    _assert_unavailable(await filter_flows_by_app(mock_client, app_name="Google"))


@pytest.mark.asyncio
async def test_filter_flows_by_client_returns_unavailable(mock_client):
    from unifi_mcp.tools.network.traffic_flows import filter_flows_by_client
    _assert_unavailable(await filter_flows_by_client(mock_client, client_ip="192.168.1.100"))


def test_traffic_flows_tools_list():
    from unifi_mcp.tools.network.traffic_flows import TOOLS
    assert len(TOOLS) == 4
