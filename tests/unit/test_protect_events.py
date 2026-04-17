import pytest

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.config import UnifiConfig


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
async def test_list_motion_events_returns_unavailable(mock_client):
    from unifi_mcp.tools.protect.events import list_motion_events
    _assert_unavailable(await list_motion_events(mock_client))


@pytest.mark.asyncio
async def test_list_smart_detections_returns_unavailable(mock_client):
    from unifi_mcp.tools.protect.events import list_smart_detections
    _assert_unavailable(await list_smart_detections(mock_client))


def test_events_tools_list():
    from unifi_mcp.tools.protect.events import TOOLS
    assert len(TOOLS) == 2
