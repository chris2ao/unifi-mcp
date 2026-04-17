import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.config import UnifiConfig

FIXTURES = Path(__file__).parent.parent / "fixtures" / "protect"
BASE = "https://192.168.1.1"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


@respx.mock
@pytest.mark.asyncio
async def test_list_nvrs_normalizes_single_object_response(mock_client):
    from unifi_mcp.tools.protect.devices import list_nvrs

    respx.get(f"{BASE}/proxy/protect/integration/v1/nvrs").mock(
        return_value=httpx.Response(200, json=load("nvrs.json"))
    )
    result = await list_nvrs(mock_client)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["name"] == "UDM Pro"
    assert result[0]["model_key"] == "nvr"


@respx.mock
@pytest.mark.asyncio
async def test_get_nvr_stats_returns_raw_record(mock_client):
    from unifi_mcp.tools.protect.devices import get_nvr_stats

    respx.get(f"{BASE}/proxy/protect/integration/v1/nvrs").mock(
        return_value=httpx.Response(200, json=load("nvrs.json"))
    )
    result = await get_nvr_stats(mock_client)
    assert result["name"] == "UDM Pro"
    assert "doorbellSettings" in result


def test_devices_tools_list():
    from unifi_mcp.tools.protect.devices import TOOLS
    assert len(TOOLS) == 3


CAM_ID = "000000000000000000000001"


@pytest.mark.asyncio
async def test_reboot_camera_returns_product_unavailable(mock_client):
    from unifi_mcp.tools.protect.devices import reboot_camera

    result = await reboot_camera(mock_client, camera_id=CAM_ID, confirm=True)
    assert result["error"] is True
    assert result["category"] == "PRODUCT_UNAVAILABLE"
    assert "reboot" in result["message"].lower()


@pytest.mark.asyncio
async def test_reboot_camera_does_not_call_api(mock_client):
    from unifi_mcp.tools.protect.devices import reboot_camera

    with respx.mock(assert_all_called=False) as mocker:
        route = mocker.post(f"{BASE}/proxy/protect/integration/v1/cameras/{CAM_ID}/reboot")
        await reboot_camera(mock_client, camera_id=CAM_ID, confirm=True)
        assert not route.called
