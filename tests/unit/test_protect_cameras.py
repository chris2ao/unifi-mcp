import base64
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
CAM_ID = "000000000000000000000001"


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
async def test_list_cameras_summarizes_records(mock_client):
    from unifi_mcp.tools.protect.cameras import list_cameras

    respx.get(f"{BASE}/proxy/protect/integration/v1/cameras").mock(
        return_value=httpx.Response(200, json=load("cameras.json"))
    )
    result = await list_cameras(mock_client)
    assert len(result) >= 1
    assert result[0]["id"] == CAM_ID
    assert result[0]["name"] == "G5 PTZ"
    assert result[0]["state"] == "CONNECTED"
    assert "person" in result[0]["smart_detect_types"]


@respx.mock
@pytest.mark.asyncio
async def test_get_camera_returns_full_record(mock_client):
    from unifi_mcp.tools.protect.cameras import get_camera

    respx.get(f"{BASE}/proxy/protect/integration/v1/cameras/{CAM_ID}").mock(
        return_value=httpx.Response(200, json=load("camera_detail.json"))
    )
    result = await get_camera(mock_client, camera_id=CAM_ID)
    assert result["id"] == CAM_ID
    assert result["mac"] == "AABBCC000001"
    assert "featureFlags" in result


@respx.mock
@pytest.mark.asyncio
async def test_get_camera_snapshot_returns_base64(mock_client):
    from unifi_mcp.tools.protect.cameras import get_camera_snapshot

    payload = b"\xff\xd8\xff\xe0fakejpegbytes"
    respx.get(f"{BASE}/proxy/protect/integration/v1/cameras/{CAM_ID}/snapshot").mock(
        return_value=httpx.Response(
            200, content=payload, headers={"content-type": "image/jpeg"}
        )
    )
    result = await get_camera_snapshot(mock_client, camera_id=CAM_ID)
    assert result["camera_id"] == CAM_ID
    assert result["content_type"] == "image/jpeg"
    assert result["size_bytes"] == len(payload)
    assert base64.b64decode(result["image_base64"]) == payload


@respx.mock
@pytest.mark.asyncio
async def test_list_liveviews(mock_client):
    from unifi_mcp.tools.protect.cameras import list_liveviews

    respx.get(f"{BASE}/proxy/protect/integration/v1/liveviews").mock(
        return_value=httpx.Response(200, json=load("liveviews.json"))
    )
    result = await list_liveviews(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "Default"
    assert result[0]["is_default"] is True
    assert result[0]["slot_count"] == 3


def test_camera_tools_list():
    from unifi_mcp.tools.protect.cameras import TOOLS
    assert len(TOOLS) == 7


@respx.mock
@pytest.mark.asyncio
async def test_update_camera_name_patches_and_invalidates_cache(mock_client):
    from unifi_mcp.tools.protect.cameras import update_camera_name

    route = respx.patch(
        f"{BASE}/proxy/protect/integration/v1/cameras/{CAM_ID}"
    ).mock(
        return_value=httpx.Response(200, json={"id": CAM_ID, "name": "Front Porch"})
    )

    # Prime the cache so we can verify invalidation
    mock_client.cache.set(f"protect_cameras:/proxy/protect/integration/v1/cameras", [{"stale": True}], 60.0)

    result = await update_camera_name(mock_client, camera_id=CAM_ID, name="Front Porch")

    assert route.called
    assert route.calls.last.request.content == b'{"name":"Front Porch"}'
    assert result == {
        "executed": True,
        "action": "update_camera_name",
        "camera_id": CAM_ID,
        "name": "Front Porch",
    }
    assert mock_client.cache.get(f"protect_cameras:/proxy/protect/integration/v1/cameras") is None


@pytest.mark.asyncio
async def test_set_camera_recording_mode_returns_product_unavailable(mock_client):
    from unifi_mcp.tools.protect.cameras import set_camera_recording_mode

    result = await set_camera_recording_mode(mock_client, camera_id=CAM_ID, mode="always")
    assert result["error"] is True
    assert result["category"] == "PRODUCT_UNAVAILABLE"
    assert "recording-mode" in result["message"]


@pytest.mark.asyncio
async def test_set_camera_recording_mode_does_not_call_api(mock_client):
    from unifi_mcp.tools.protect.cameras import set_camera_recording_mode

    with respx.mock(assert_all_called=False) as mocker:
        route = mocker.patch(f"{BASE}/proxy/protect/integration/v1/cameras/{CAM_ID}")
        await set_camera_recording_mode(
            mock_client, camera_id=CAM_ID, mode="always", confirm=True,
        )
        assert not route.called


@pytest.mark.asyncio
async def test_ptz_camera_returns_product_unavailable(mock_client):
    from unifi_mcp.tools.protect.cameras import ptz_camera

    result = await ptz_camera(mock_client, camera_id=CAM_ID, pan=90.0, tilt=0.0)
    assert result["error"] is True
    assert result["category"] == "PRODUCT_UNAVAILABLE"
    assert "PTZ" in result["message"]


@pytest.mark.asyncio
async def test_ptz_camera_does_not_call_api_even_with_confirm(mock_client):
    from unifi_mcp.tools.protect.cameras import ptz_camera

    with respx.mock(assert_all_called=False) as mocker:
        route = mocker.post(f"{BASE}/proxy/protect/integration/v1/cameras/{CAM_ID}/ptz")
        await ptz_camera(mock_client, camera_id=CAM_ID, preset_id="home", confirm=True)
        assert not route.called
