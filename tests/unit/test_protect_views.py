import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.errors import UnifiError
from unifi_mcp.tools.protect import views

FIXTURES = Path(__file__).parent.parent / "fixtures" / "protect"
HOST = "https://192.0.2.1"
BASE = f"{HOST}/proxy/protect/integration/v1"
LV = "00000000-0000-0000-0000-0000000000a4"
VW = "00000000-0000-0000-0000-0000000000a5"
CAM = "00000000-0000-0000-0000-0000000000a1"


def fx(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", HOST)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def test_module_conventions():
    assert views.GROUP == "cameras"
    assert views.TIER2_TOOLS == {}
    assert len(views.TOOLS) == 6


@respx.mock
async def test_get_liveview(mock_client):
    respx.get(f"{BASE}/liveviews/{LV}").mock(return_value=httpx.Response(200, json=fx("views_liveview.json")))
    result = await views.get_liveview(mock_client, LV)
    assert result["name"] == "Front Cams" and result["layout"] == 2
    assert result["slots"][1]["cycle_mode"] == "motion"
    assert len(result["slots"][1]["cameras"]) == 2


@respx.mock
async def test_get_liveview_wrapped_not_found_and_empty(mock_client):
    route = respx.get(f"{BASE}/liveviews/{LV}").mock(
        return_value=httpx.Response(200, json={"data": fx("views_liveview.json")}))
    assert (await views.get_liveview(mock_client, LV))["id"] == LV
    mock_client.cache.invalidate("protect_liveviews")
    route.mock(return_value=httpx.Response(404, json={"error": "nf"}))
    assert (await views.get_liveview(mock_client, LV))["category"] == "NOT_FOUND"
    route.mock(return_value=httpx.Response(200, json={}))
    assert (await views.get_liveview(mock_client, LV))["category"] == "NOT_FOUND"


@respx.mock
async def test_non_404_errors_propagate(mock_client):
    respx.get(f"{BASE}/liveviews/{LV}").mock(return_value=httpx.Response(403))
    with pytest.raises(UnifiError):
        await views.get_liveview(mock_client, LV)


@respx.mock
async def test_create_liveview(mock_client):
    route = respx.post(f"{BASE}/liveviews").mock(return_value=httpx.Response(200, json=fx("views_liveview.json")))
    slots = [{"cameras": [CAM]}, {"cameras": [CAM], "cycle_mode": "motion", "cycle_interval": 30}]
    result = await views.create_liveview(mock_client, "Front Cams", 2, slots, is_global=True)
    assert result["executed"] is True and result["liveview"]["id"] == LV
    sent = json.loads(route.calls[0].request.content)
    assert sent == {
        "name": "Front Cams", "layout": 2, "isGlobal": True,
        "slots": [
            {"cameras": [CAM], "cycleMode": "time", "cycleInterval": 10},
            {"cameras": [CAM], "cycleMode": "motion", "cycleInterval": 30},
        ],
    }
    assert "cycle_mode" in slots[1]  # input untouched


@respx.mock
async def test_create_liveview_empty_response(mock_client):
    respx.post(f"{BASE}/liveviews").mock(return_value=httpx.Response(200, json={}))
    result = await views.create_liveview(mock_client, "A", 1, [{"cameras": [CAM]}])
    assert result["executed"] is False


@pytest.mark.parametrize("args", [
    ("", 1, [{"cameras": [CAM]}]),
    ("A", 0, [{"cameras": [CAM]}]),
    ("A", 27, [{"cameras": [CAM]}]),
    ("A", True, [{"cameras": [CAM]}]),
    ("A", 2, [{"cameras": [CAM]}]),
    ("A", 1, []),
    ("A", 1, ["x"]),
    ("A", 1, [{"cameras": []}]),
    ("A", 1, [{"cameras": ["a/b"]}]),
    ("A", 1, [{"cameras": [CAM], "cycleMode": "random"}]),
    ("A", 1, [{"cameras": [CAM], "cycleInterval": 0}]),
    ("A", 1, [{"cameras": [CAM], "cycleInterval": "10"}]),
])
async def test_create_liveview_validation(mock_client, args):
    result = await views.create_liveview(mock_client, *args)
    assert result["error"] is True and result["category"] == "VALIDATION_ERROR"


async def test_create_liveview_bad_global(mock_client):
    result = await views.create_liveview(mock_client, "A", 1, [{"cameras": [CAM]}], is_global="yes")
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_update_liveview(mock_client):
    route = respx.patch(f"{BASE}/liveviews/{LV}").mock(return_value=httpx.Response(200, json=fx("views_liveview.json")))
    result = await views.update_liveview(mock_client, LV, {"name": "Renamed", "is_default": True})
    assert result["executed"] is True
    assert json.loads(route.calls[0].request.content) == {"name": "Renamed", "isDefault": True}


@respx.mock
async def test_update_liveview_slots_and_layout(mock_client):
    route = respx.patch(f"{BASE}/liveviews/{LV}").mock(return_value=httpx.Response(200, json=fx("views_liveview.json")))
    await views.update_liveview(mock_client, LV, {"layout": 1, "slots": [{"cameras": [CAM]}]})
    sent = json.loads(route.calls[0].request.content)
    assert sent["slots"][0]["cycleMode"] == "time"


@respx.mock
async def test_update_liveview_not_found_and_noop(mock_client):
    route = respx.patch(f"{BASE}/liveviews/{LV}").mock(return_value=httpx.Response(404, json={"error": "nf"}))
    assert (await views.update_liveview(mock_client, LV, {"name": "x"}))["category"] == "NOT_FOUND"
    route.mock(return_value=httpx.Response(200, json={}))
    assert (await views.update_liveview(mock_client, LV, {"name": "x"}))["executed"] is False


async def test_update_liveview_validation(mock_client):
    for lv_id, updates in [("a/b", {"name": "x"}), (LV, {}), (LV, "x"), (LV, {"bogus": 1}),
                           (LV, {"layout": 99}), (LV, {"layout": 2, "slots": [{"cameras": [CAM]}]})]:
        result = await views.update_liveview(mock_client, lv_id, updates)
        assert result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_list_viewers(mock_client):
    respx.get(f"{BASE}/viewers").mock(return_value=httpx.Response(200, json=fx("views_viewers.json")))
    result = await views.list_viewers(mock_client)
    assert len(result) == 2
    assert result[0]["liveview_id"] == LV and result[0]["state"] == "CONNECTED"
    assert result[1]["name"] is None and result[1]["liveview_id"] is None


@respx.mock
async def test_list_viewers_shapes(mock_client):
    route = respx.get(f"{BASE}/viewers").mock(return_value=httpx.Response(200, json={"data": fx("views_viewers.json")}))
    assert len(await views.list_viewers(mock_client)) == 2
    mock_client.cache.invalidate("protect_viewers")
    route.mock(return_value=httpx.Response(200, json=[]))
    assert await views.list_viewers(mock_client) == []


@respx.mock
async def test_get_viewer(mock_client):
    route = respx.get(f"{BASE}/viewers/{VW}").mock(return_value=httpx.Response(200, json=fx("views_viewers.json")[0]))
    assert (await views.get_viewer(mock_client, VW))["stream_limit"] == 16
    mock_client.cache.invalidate("protect_viewers")
    route.mock(return_value=httpx.Response(404, json={"error": "nf"}))
    assert (await views.get_viewer(mock_client, VW))["category"] == "NOT_FOUND"
    route.mock(return_value=httpx.Response(200, json={}))
    mock_client.cache.invalidate("protect_viewers")
    assert (await views.get_viewer(mock_client, VW))["category"] == "NOT_FOUND"
    assert (await views.get_viewer(mock_client, "a/b"))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_set_viewer_liveview(mock_client):
    route = respx.patch(f"{BASE}/viewers/{VW}").mock(return_value=httpx.Response(200, json=fx("views_viewers.json")[0]))
    result = await views.set_viewer_liveview(mock_client, VW, LV)
    assert result["executed"] is True
    assert json.loads(route.calls[0].request.content) == {"liveview": LV}
    await views.set_viewer_liveview(mock_client, VW, None)
    assert json.loads(route.calls[1].request.content) == {"liveview": None}


@respx.mock
async def test_set_viewer_liveview_errors(mock_client):
    route = respx.patch(f"{BASE}/viewers/{VW}").mock(return_value=httpx.Response(404, json={"error": "nf"}))
    assert (await views.set_viewer_liveview(mock_client, VW, LV))["category"] == "NOT_FOUND"
    route.mock(return_value=httpx.Response(200, json={}))
    assert (await views.set_viewer_liveview(mock_client, VW, LV))["executed"] is False
    assert (await views.set_viewer_liveview(mock_client, "a b", LV))["category"] == "VALIDATION_ERROR"
    assert (await views.set_viewer_liveview(mock_client, VW, "../x"))["category"] == "VALIDATION_ERROR"
