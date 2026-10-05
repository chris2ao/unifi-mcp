import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.protect import camera_controls as cc

FIXTURES = Path(__file__).parent.parent / "fixtures" / "protect"
BASE = "https://192.168.1.1"
API = f"{BASE}/proxy/protect/integration/v1/cameras"
PTZ_ID = "00000000-0000-0000-0000-0000000000a1"
FIXED_ID = "00000000-0000-0000-0000-0000000000a2"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def load(name):
    return json.loads((FIXTURES / name).read_text())


def mock_cam(cam_id=PTZ_ID, fixture="camera_ptz.json"):
    return respx.get(f"{API}/{cam_id}").mock(return_value=httpx.Response(200, json=load(fixture)))


def test_module_conventions():
    assert cc.GROUP == "cameras"
    assert set(cc.TIER2_TOOLS) == {
        "update_camera_settings", "disable_camera_mic_permanently",
        "create_rtsps_stream", "delete_rtsps_stream",
    }
    names = {f.__name__ for f in cc.TOOLS}
    assert set(cc.TIER2_TOOLS) <= names and "ptz_camera" in names
    assert "ptz_camera" not in cc.TIER2_TOOLS


# --- ptz ---

@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("action,slot,path", [
    ("goto", 2, "ptz/goto/2"), ("goto", "-1", "ptz/goto/-1"),
    ("patrol_start", 0, "ptz/patrol/start/0"), ("patrol_stop", None, "ptz/patrol/stop"),
])
async def test_ptz_actions(mock_client, action, slot, path):
    mock_cam()
    route = respx.post(f"{API}/{PTZ_ID}/{path}").mock(return_value=httpx.Response(204))
    result = await cc.ptz_camera(mock_client, PTZ_ID, action, slot)
    assert route.called
    assert result["executed"] is True and result["action"] == "ptz_camera"
    assert result["ptz_action"] == action


@respx.mock
@pytest.mark.asyncio
async def test_ptz_rejects_non_ptz_camera(mock_client):
    mock_cam(FIXED_ID, "camera_fixed.json")
    with respx.mock(assert_all_called=False) as m:
        route = m.post(url__regex=r".*/ptz/.*")
        result = await cc.ptz_camera(mock_client, FIXED_ID, "goto", 0)
        assert not route.called
    assert result["category"] == "VALIDATION_ERROR" and "PTZ" in result["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    (PTZ_ID, "spin", 0), (PTZ_ID, "goto", None), (PTZ_ID, "goto", "abc"),
    (PTZ_ID, "goto", -2), (PTZ_ID, "goto", True), (PTZ_ID, "patrol_start", 5),
    (PTZ_ID, "patrol_start", -1), ("../x", "goto", 0), ("", "patrol_stop", None),
])
async def test_ptz_validation(mock_client, args):
    result = await cc.ptz_camera(mock_client, *args)
    assert result["error"] is True and result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_ptz_not_found(mock_client):
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(404))
    result = await cc.ptz_camera(mock_client, PTZ_ID, "patrol_stop")
    assert result["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_ptz_server_error_propagates(mock_client):
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(401))
    with pytest.raises(Exception):
        await cc.ptz_camera(mock_client, PTZ_ID, "patrol_stop")


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["data_obj", "data_list", "bare_list"])
async def test_camera_shape_variance(mock_client, shape):
    cam = load("camera_ptz.json")
    body = {"data_obj": {"data": cam}, "data_list": {"data": [cam]}, "bare_list": [cam]}[shape]
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json=body))
    respx.post(f"{API}/{PTZ_ID}/ptz/patrol/stop").mock(return_value=httpx.Response(204))
    assert (await cc.ptz_camera(mock_client, PTZ_ID, "patrol_stop"))["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_empty_camera_is_not_found(mock_client):
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await cc.ptz_camera(mock_client, PTZ_ID, "patrol_stop"))["category"] == "NOT_FOUND"


# --- update_camera_settings ---

@respx.mock
@pytest.mark.asyncio
async def test_update_settings_preview_shows_current_and_proposed(mock_client):
    mock_cam()
    with respx.mock(assert_all_called=False) as m:
        patch = m.patch(f"{API}/{PTZ_ID}")
        first = await cc.update_camera_settings(mock_client, PTZ_ID, {"micVolume": 40})
        second = await cc.update_camera_settings(mock_client, PTZ_ID, {"micVolume": 40})
        assert not patch.called
    assert first["preview"] is True and first == second
    assert first["changes"]["micVolume"] == {"current": 80, "proposed": 40}


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_confirm_patches_and_invalidates(mock_client):
    mock_cam()
    patch = respx.patch(f"{API}/{PTZ_ID}").mock(
        return_value=httpx.Response(200, json={**load("camera_ptz.json"), "micVolume": 40})
    )
    settings = {"micVolume": 40, "hdrType": "off", "videoMode": "sport",
                "ledSettings": {"isEnabled": False},
                "osdSettings": {"isDateEnabled": False, "overlayLocation": "topRight"},
                "smartDetectSettings": {"objectTypes": ["person"], "audioTypes": []},
                "lcdMessage": {"type": "CUSTOM_MESSAGE", "text": "Hi", "resetAt": None}}
    result = await cc.update_camera_settings(mock_client, PTZ_ID, settings, confirm=True)
    assert result["executed"] is True and result["response"]["micVolume"] == 40
    assert json.loads(patch.calls.last.request.content) == settings


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_empty_response_is_noop(mock_client):
    mock_cam()
    respx.patch(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json={}))
    result = await cc.update_camera_settings(mock_client, PTZ_ID, {"micVolume": 10}, confirm=True)
    assert result["executed"] is False and "no-op" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_does_not_mutate_input(mock_client):
    mock_cam()
    settings = {"micVolume": 10}
    await cc.update_camera_settings(mock_client, PTZ_ID, settings)
    assert settings == {"micVolume": 10}


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [
    {}, "x", {"name": "New"}, {"bogus": 1}, {"micVolume": 101}, {"micVolume": -1}, {"micVolume": 0},
    {"micVolume": True}, {"videoMode": "turbo"}, {"hdrType": "max"},
    {"ledSettings": {"isEnabled": "yes"}}, {"ledSettings": {}}, {"ledSettings": {"x": True}},
    {"osdSettings": {"overlayLocation": "middle"}}, {"osdSettings": {"isNameEnabled": 1}},
    {"osdSettings": "x"}, {"lcdMessage": {"type": "NOPE"}}, {"lcdMessage": {}},
    {"lcdMessage": {"type": "CUSTOM_MESSAGE"}}, {"lcdMessage": {"type": "DO_NOT_DISTURB", "resetAt": "x"}},
    {"lcdMessage": {"type": "DO_NOT_DISTURB", "extra": 1}},
    {"smartDetectSettings": {"objectTypes": ["dragon"]}}, {"smartDetectSettings": {"objectTypes": "person"}},
    {"smartDetectSettings": {"audioTypes": ["alrmBark"], "x": 1}}, {"smartDetectSettings": {}},
])
async def test_update_settings_validation(mock_client, settings):
    mock_cam()
    result = await cc.update_camera_settings(mock_client, PTZ_ID, settings, confirm=True)
    assert result["error"] is True and result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_video_mode_checked_against_camera_flags(mock_client):
    mock_cam(FIXED_ID, "camera_fixed.json")
    result = await cc.update_camera_settings(mock_client, FIXED_ID, {"videoMode": "slowShutter"})
    assert result["category"] == "VALIDATION_ERROR" and "default, sport" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_unsupported_smart_type(mock_client):
    cam = load("camera_ptz.json")
    cam["featureFlags"] = {**cam["featureFlags"], "smartDetectTypes": ["person"]}
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json=cam))
    result = await cc.update_camera_settings(
        mock_client, PTZ_ID, {"smartDetectSettings": {"objectTypes": ["vehicle"]}},
    )
    assert "not supported" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_not_found_and_bad_id(mock_client):
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(404))
    assert (await cc.update_camera_settings(mock_client, PTZ_ID, {"micVolume": 1}))["category"] == "NOT_FOUND"
    assert (await cc.update_camera_settings(mock_client, "a/b", {"micVolume": 1}))["category"] == "VALIDATION_ERROR"


# --- set_camera_led ---

@respx.mock
@pytest.mark.asyncio
async def test_set_camera_led(mock_client):
    patch = respx.patch(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json=load("camera_ptz.json")))
    result = await cc.set_camera_led(mock_client, PTZ_ID, False)
    assert json.loads(patch.calls.last.request.content) == {"ledSettings": {"isEnabled": False}}
    assert result["executed"] is True and result["enabled"] is False


@respx.mock
@pytest.mark.asyncio
async def test_set_camera_led_noop_and_validation(mock_client):
    respx.patch(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json={}))
    assert (await cc.set_camera_led(mock_client, PTZ_ID, True))["executed"] is False
    assert (await cc.set_camera_led(mock_client, PTZ_ID, "on"))["category"] == "VALIDATION_ERROR"
    assert (await cc.set_camera_led(mock_client, "..", True))["category"] == "VALIDATION_ERROR"


# --- disable mic ---

@respx.mock
@pytest.mark.asyncio
async def test_disable_mic_preview_is_loud(mock_client):
    mock_cam()
    with respx.mock(assert_all_called=False) as m:
        post = m.post(f"{API}/{PTZ_ID}/disable-mic-permanently")
        result = await cc.disable_camera_mic_permanently(mock_client, PTZ_ID)
        assert not post.called
    assert result["preview"] is True and "IRREVERSIBLE" in result["impact"]
    assert result["camera_name"] == "Yard PTZ"


@respx.mock
@pytest.mark.asyncio
async def test_disable_mic_confirm_and_noop(mock_client):
    mock_cam()
    route = respx.post(f"{API}/{PTZ_ID}/disable-mic-permanently").mock(
        return_value=httpx.Response(200, json={**load("camera_ptz.json"), "isMicEnabled": False})
    )
    result = await cc.disable_camera_mic_permanently(mock_client, PTZ_ID, confirm=True)
    assert route.called and result["executed"] is True
    route.mock(return_value=httpx.Response(200, json={}))
    assert (await cc.disable_camera_mic_permanently(mock_client, PTZ_ID, confirm=True))["executed"] is False


@respx.mock
@pytest.mark.asyncio
async def test_disable_mic_errors(mock_client):
    assert (await cc.disable_camera_mic_permanently(mock_client, "a b"))["category"] == "VALIDATION_ERROR"
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(404))
    assert (await cc.disable_camera_mic_permanently(mock_client, PTZ_ID))["category"] == "NOT_FOUND"


# --- rtsps ---

@respx.mock
@pytest.mark.asyncio
async def test_get_rtsps_masks_token_by_default(mock_client):
    respx.get(f"{API}/{PTZ_ID}/rtsps-stream").mock(return_value=httpx.Response(200, json=load("camera_rtsps.json")))
    result = await cc.get_rtsps_streams(mock_client, PTZ_ID)
    assert result["streams"]["high"] == "rtsps://192.0.2.10:7441/***?enableSrtp"
    assert result["streams"]["low"] is None and "FAKETOKEN" not in json.dumps(result)


@respx.mock
@pytest.mark.asyncio
async def test_get_rtsps_reveal_and_variants(mock_client):
    raw = load("camera_rtsps.json")
    respx.get(f"{API}/{PTZ_ID}/rtsps-stream").mock(return_value=httpx.Response(200, json={"data": raw}))
    result = await cc.get_rtsps_streams(mock_client, PTZ_ID, reveal_urls=True)
    assert result["streams"]["high"] == raw["high"] and result["revealed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_get_rtsps_errors(mock_client):
    assert (await cc.get_rtsps_streams(mock_client, "x/y"))["category"] == "VALIDATION_ERROR"
    respx.get(f"{API}/{PTZ_ID}/rtsps-stream").mock(return_value=httpx.Response(404))
    assert (await cc.get_rtsps_streams(mock_client, PTZ_ID))["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_create_rtsps_preview_and_confirm(mock_client):
    mock_cam()
    with respx.mock(assert_all_called=False) as m:
        post = m.post(f"{API}/{PTZ_ID}/rtsps-stream")
        preview = await cc.create_rtsps_stream(mock_client, PTZ_ID, ["high", "high", "low"])
        assert not post.called
    assert preview["preview"] is True and preview["qualities"] == ["high", "low"]
    route = respx.post(f"{API}/{PTZ_ID}/rtsps-stream").mock(
        return_value=httpx.Response(200, json={"high": "rtsps://192.0.2.10:7441/SECRET?enableSrtp"})
    )
    result = await cc.create_rtsps_stream(mock_client, PTZ_ID, ["high"], confirm=True)
    assert json.loads(route.calls.last.request.content) == {"qualities": ["high"]}
    assert result["executed"] is True and "SECRET" not in json.dumps(result)


@respx.mock
@pytest.mark.asyncio
async def test_create_rtsps_noop_and_validation(mock_client):
    mock_cam()
    respx.post(f"{API}/{PTZ_ID}/rtsps-stream").mock(return_value=httpx.Response(200, json={}))
    assert (await cc.create_rtsps_stream(mock_client, PTZ_ID, ["high"], confirm=True))["executed"] is False
    for bad in ([], "high", ["ultra"], ["package"]):
        assert (await cc.create_rtsps_stream(mock_client, PTZ_ID, bad))["category"] == "VALIDATION_ERROR"
    assert (await cc.create_rtsps_stream(mock_client, "a/b", ["high"]))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_create_rtsps_camera_not_found(mock_client):
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(404))
    assert (await cc.create_rtsps_stream(mock_client, PTZ_ID, ["high"]))["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_package_quality_allowed_when_camera_has_package_cam(mock_client):
    cam = {**load("camera_ptz.json"), "hasPackageCamera": True}
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json=cam))
    assert (await cc.create_rtsps_stream(mock_client, PTZ_ID, ["package"]))["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_rtsps_preview_and_confirm(mock_client):
    mock_cam()
    preview = await cc.delete_rtsps_stream(mock_client, PTZ_ID, ["high", "medium"])
    assert preview["preview"] is True and "impact" in preview
    route = respx.delete(f"{API}/{PTZ_ID}/rtsps-stream").mock(return_value=httpx.Response(204))
    result = await cc.delete_rtsps_stream(mock_client, PTZ_ID, ["high", "medium"], confirm=True)
    assert result["executed"] is True
    assert route.calls.last.request.url.params.get_list("qualities") == ["high", "medium"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_rtsps_validation(mock_client):
    assert (await cc.delete_rtsps_stream(mock_client, PTZ_ID, []))["category"] == "VALIDATION_ERROR"
    assert (await cc.delete_rtsps_stream(mock_client, "..", ["high"]))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_update_settings_unsupported_audio_type(mock_client):
    cam = load("camera_ptz.json")
    cam["featureFlags"] = {**cam["featureFlags"], "smartDetectAudioTypes": []}
    respx.get(f"{API}/{PTZ_ID}").mock(return_value=httpx.Response(200, json=cam))
    result = await cc.update_camera_settings(
        mock_client, PTZ_ID, {"smartDetectSettings": {"audioTypes": ["alrmBark"]}},
    )
    assert "not supported" in result["message"] and "none" in result["message"]


def test_mask_streams_recurses_and_homekit_excluded():
    wrapped = {"data": {"high": "rtsps://h:7441/SECRET?x=1", "low": None}, "list": ["rtsps://h/T"]}
    masked = cc._mask_streams(wrapped, False)
    assert "SECRET" not in str(masked) and "/T" not in str(masked["list"])
    assert cc._mask_streams(wrapped, True) is wrapped
    from unifi_mcp.tools.protect.camera_settings_validation import validate_settings
    cam = {"featureFlags": {"videoModes": ["default", "homekit"]}}
    assert validate_settings({"videoMode": "homekit"}, cam)["category"] == "VALIDATION_ERROR"
    assert validate_settings({"videoMode": "default"}, cam) is None


def test_is_ptz_unknown_type_is_none():
    assert cc._is_ptz({"type": None}) is None
    assert cc._is_ptz({"type": "UVC AI 360"}) is False
    assert cc._is_ptz({"type": "G5 PTZ"}) is True
