"""Tests for generic Protect accessory device tools and users."""
import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.protect import accessories as acc

FIXTURES = Path(__file__).parent.parent / "fixtures" / "protect"
BASE = "https://192.168.1.1/proxy/protect/integration/v1"
SIREN = "000000000000000000000002"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


def load(name):
    return json.loads((FIXTURES / name).read_text())


def is_validation(r):
    return r.get("error") is True and r.get("category") == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_list_devices_bare_list(mock_client):
    respx.get(f"{BASE}/sirens").mock(return_value=httpx.Response(200, json=load("accessory_sirens.json")))
    r = await acc.list_protect_devices(mock_client, "sirens")
    assert len(r) == 1 and r[0]["name"] == "Hall Siren"


@respx.mock
@pytest.mark.asyncio
async def test_list_devices_paginated_and_empty(mock_client):
    respx.get(f"{BASE}/lights").mock(return_value=httpx.Response(
        200, json={"data": load("accessory_lights.json"), "totalCount": 1}))
    respx.get(f"{BASE}/chimes").mock(return_value=httpx.Response(200, json=[]))
    assert len(await acc.list_protect_devices(mock_client, "lights")) == 1
    assert await acc.list_protect_devices(mock_client, "chimes") == []


@respx.mock
@pytest.mark.asyncio
async def test_list_devices_scrubs_secrets(mock_client):
    item = {**load("accessory_bridges.json")[0], "rtspsToken": "x", "wifi": {"password": "p", "ssid": "Home"}}
    respx.get(f"{BASE}/bridges").mock(return_value=httpx.Response(200, json=[item]))
    r = await acc.list_protect_devices(mock_client, "bridges")
    assert "rtspsToken" not in r[0] and r[0]["wifi"] == {"ssid": "Home"}


@pytest.mark.asyncio
async def test_list_devices_bad_kind(mock_client):
    r = await acc.list_protect_devices(mock_client, "cameras")
    assert is_validation(r[0])


@respx.mock
@pytest.mark.asyncio
async def test_get_device_variants(mock_client):
    siren = load("accessory_sirens.json")[0]
    respx.get(f"{BASE}/sirens/{SIREN}").mock(return_value=httpx.Response(200, json=siren))
    assert (await acc.get_protect_device(mock_client, "sirens", SIREN))["volume"] == 50
    respx.get(f"{BASE}/sirens/wrapped").mock(return_value=httpx.Response(200, json={"data": siren}))
    assert (await acc.get_protect_device(mock_client, "sirens", "wrapped"))["id"] == siren["id"]
    respx.get(f"{BASE}/sirens/empty").mock(return_value=httpx.Response(200, json={}))
    r = await acc.get_protect_device(mock_client, "sirens", "empty")
    assert r["category"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_get_device_validation(mock_client):
    assert is_validation(await acc.get_protect_device(mock_client, "nope", SIREN))
    assert is_validation(await acc.get_protect_device(mock_client, "sirens", "../x"))


@respx.mock
@pytest.mark.asyncio
async def test_update_preview_shows_current_and_proposed(mock_client):
    route = respx.get(f"{BASE}/sirens/{SIREN}").mock(
        return_value=httpx.Response(200, json=load("accessory_sirens.json")[0]))
    patch = respx.patch(f"{BASE}/sirens/{SIREN}")
    r = await acc.update_protect_device(mock_client, "sirens", SIREN, {"volume": 70})
    assert r["preview"] is True and r["current"] == {"volume": 50} and r["proposed"] == {"volume": 70}
    assert route.called and not patch.called
    again = await acc.update_protect_device(mock_client, "sirens", SIREN, {"volume": 70})
    assert again == r


@respx.mock
@pytest.mark.asyncio
async def test_update_preview_mic_impact_and_notfound(mock_client):
    speaker = load("accessory_speakers.json")[0]
    respx.get(f"{BASE}/speakers/s1").mock(return_value=httpx.Response(200, json=speaker))
    r = await acc.update_protect_device(mock_client, "speakers", "s1", {"isMicEnabled": False})
    assert "impact" in r
    respx.get(f"{BASE}/speakers/s2").mock(return_value=httpx.Response(200, json={}))
    r = await acc.update_protect_device(mock_client, "speakers", "s2", {"volume": 5})
    assert r["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_update_confirmed(mock_client):
    patch = respx.patch(f"{BASE}/sirens/{SIREN}").mock(
        return_value=httpx.Response(200, json={"id": SIREN, "volume": 70}))
    r = await acc.update_protect_device(mock_client, "sirens", SIREN, {"volume": 70}, confirm=True)
    assert r["executed"] is True and r["response"]["volume"] == 70
    assert json.loads(patch.calls[0].request.content) == {"volume": 70}


@respx.mock
@pytest.mark.asyncio
async def test_update_confirmed_silent_noop(mock_client):
    respx.patch(f"{BASE}/bridges/b1").mock(return_value=httpx.Response(200, json={}))
    r = await acc.update_protect_device(mock_client, "bridges", "b1", {"name": "New"}, confirm=True)
    assert r["executed"] is False and "nothing" in r["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,settings", [
    ("sirens", {}), ("sirens", "x"), ("sirens", {"bogus": 1}), ("bridges", {"volume": 5}),
    ("sirens", {"volume": 0}), ("sirens", {"volume": 101}), ("sirens", {"volume": "5"}),
    ("speakers", {"volume": -1}), ("speakers", {"micVolume": 1.5}), ("speakers", {"isMicEnabled": "no"}),
    ("lights", {"name": " "}), ("lights", {"name": 3}),
])
async def test_update_validation(mock_client, kind, settings):
    assert is_validation(await acc.update_protect_device(mock_client, kind, "d1", settings))


@pytest.mark.asyncio
async def test_update_validation_bad_kind_and_id(mock_client):
    assert is_validation(await acc.update_protect_device(mock_client, "x", "d1", {"name": "a"}))
    assert is_validation(await acc.update_protect_device(mock_client, "lights", "a b", {"name": "a"}))


def test_patch_fields_allow_list():
    assert acc.PATCH_FIELDS["sirens"] == {"name", "volume", "ledSettings"}
    assert set(acc.PATCH_FIELDS) == set(acc.KINDS)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,action,out,opts,path,body", [
    ("sirens", "play", None, {"duration": 10}, f"/sirens/{SIREN}/play", {"duration": 10}),
    ("sirens", "stop", None, None, f"/sirens/{SIREN}/stop", None),
    ("sirens", "test-sound", None, None, f"/sirens/{SIREN}/test-sound", None),
    ("sirens", "test-sound", None, {"volume": 50}, f"/sirens/{SIREN}/test-sound", {"volume": 50}),
    ("relays", "activate", 1, {"toggle": True}, f"/relays/{SIREN}/outputs/1/activate", None),
    ("speakers", "test-sound", None, {"volume": 30}, f"/speakers/{SIREN}/test-sound", {"volume": 30}),
    ("relays", "activate", 0, {"state": "on", "pulseDuration": 500},
     f"/relays/{SIREN}/outputs/0/activate", {"state": "on", "pulseDuration": 500}),
    ("alarm-hubs", "trigger", "1", {"enable": True, "delay": 0, "duration": 5000},
     f"/alarm-hubs/{SIREN}/outputs/1/trigger", {"enable": True, "delay": 0, "duration": 5000}),
])
async def test_action_preview_and_confirm(mock_client, kind, action, out, opts, path, body):
    with respx.mock:
        route = respx.post(f"{BASE}{path}").mock(return_value=httpx.Response(204))
        pre = await acc.run_protect_device_action(mock_client, kind, SIREN, action, out, opts)
        assert pre["preview"] is True and "IMPACT" in pre["impact"] and not route.called
        again = await acc.run_protect_device_action(mock_client, kind, SIREN, action, out, opts)
        assert again == pre
        done = await acc.run_protect_device_action(mock_client, kind, SIREN, action, out, opts, confirm=True)
        assert done["executed"] is True and route.call_count == 1
        sent = route.calls[0].request.content
        assert (json.loads(sent) if sent else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,action,out,opts", [
    ("lights", "play", None, None),
    ("sirens", "activate", None, None),
    ("sirens", "play", "o1", None),
    ("relays", "activate", None, None),
    ("relays", "activate", "a/b", None),
    ("relays", "activate", "out1", {"state": "on"}),
    ("relays", "activate", -1, {"state": "on"}),
    ("relays", "activate", True, {"state": "on"}),
    ("relays", "activate", 0, None),
    ("relays", "activate", 0, {"pulseDuration": 100}),
    ("relays", "activate", 0, {"toggle": True, "state": "on"}),
    ("alarm-hubs", "trigger", 0, {"delay": 0}),
    ("sirens", "test-sound", None, {"volume": 0}),
    ("alarm-hubs", "trigger", None, None),
    ("sirens", "play", None, {"duration": 7}),
    ("sirens", "play", None, {"volume": 5}),
    ("sirens", "play", None, "x"),
    ("speakers", "test-sound", None, {"volume": 101}),
    ("speakers", "test-sound", None, {"volume": "9"}),
    ("relays", "activate", "o1", {"state": "maybe"}),
    ("relays", "activate", "o1", {"pulseDuration": -5}),
    ("alarm-hubs", "trigger", "o1", {"enable": "yes"}),
    ("alarm-hubs", "trigger", "o1", {"delay": 1.5}),
    ("nope", "play", None, None),
])
async def test_action_validation(mock_client, kind, action, out, opts):
    r = await acc.run_protect_device_action(mock_client, kind, SIREN, action, out, opts)
    assert is_validation(r), (kind, action, r)


@pytest.mark.asyncio
async def test_toggle_preview_has_effect_line(mock_client):
    r = await acc.run_protect_device_action(mock_client, "relays", SIREN, "activate", 0, {"toggle": True})
    assert r["preview"] is True and "TOGGLE" in r["effect"] and r["options"] == {}
    r = await acc.run_protect_device_action(
        mock_client, "relays", SIREN, "activate", 0, {"state": "off", "pulseDuration": 500})
    assert r["effect"] == "turn output 0 OFF for 500 ms"


@respx.mock
@pytest.mark.asyncio
async def test_get_device_404_is_not_found_dict(mock_client):
    respx.get(f"{BASE}/lights/nope").mock(return_value=httpx.Response(404, json={}))
    r = await acc.get_protect_device(mock_client, "lights", "nope")
    assert r["error"] is True and r["category"] == "NOT_FOUND"
    r = await acc.update_protect_device(mock_client, "lights", "nope", {"name": "x"})
    assert r["category"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_action_bad_device_id(mock_client):
    r = await acc.run_protect_device_action(mock_client, "sirens", "../x", "stop")
    assert is_validation(r)


@respx.mock
@pytest.mark.asyncio
async def test_list_users(mock_client):
    respx.get(f"{BASE}/users").mock(return_value=httpx.Response(200, json=load("accessory_users.json")))
    respx.get(f"{BASE}/ulp-users").mock(return_value=httpx.Response(200, json=load("accessory_ulp_users.json")))
    r = await acc.list_protect_users(mock_client)
    assert r["users"][0] == {"id": "000000000000000000000a01", "name": "Alex Example",
                             "email": "alex@example.com", "status": None, "source": "user"}
    assert r["ulp_users"][0]["name"] == "Sam Sample" and r["ulp_users"][0]["email"] is None
    assert r["ulp_users"][0]["status"] == "ACTIVE" and r["errors"] == []
    assert "SHOULD-NOT-LEAK" not in json.dumps(r)


@respx.mock
@pytest.mark.asyncio
async def test_list_users_partial_failure(mock_client):
    respx.get(f"{BASE}/users").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE}/ulp-users").mock(return_value=httpx.Response(404, json={}))
    r = await acc.list_protect_users(mock_client)
    assert r["users"] == [] and r["ulp_users"] == [] and len(r["errors"]) == 1


def test_as_list_variants():
    assert acc._as_list({"data": {"id": "a"}}) == [{"id": "a"}]
    assert acc._as_list({"id": "a"}) == [{"id": "a"}]
    assert acc._as_list("x") == []


def test_module_conventions():
    assert acc.GROUP == "devices"
    assert set(acc.TIER2_TOOLS) == {"update_protect_device", "run_protect_device_action"}
    assert len(acc.TOOLS) == 5
    assert "—" not in Path(acc.__file__).read_text()
