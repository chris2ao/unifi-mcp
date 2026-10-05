import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.protect import alarm

FIXTURES = Path(__file__).parent.parent / "fixtures" / "protect"
HOST = "https://192.0.2.1"
BASE = f"{HOST}/proxy/protect/integration/v1"
PID = "00000000-0000-0000-0000-0000000000a1"


def fx(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", HOST)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def test_module_conventions():
    assert alarm.GROUP == "security"
    assert set(alarm.TIER2_TOOLS) == {
        "arm_alarm", "disarm_alarm", "set_active_arm_profile", "create_arm_profile",
        "update_arm_profile", "delete_arm_profile", "trigger_alarm_webhook",
    }
    assert {t.__name__ for t in alarm.TOOLS} >= set(alarm.TIER2_TOOLS)


@respx.mock
async def test_list_arm_profiles(mock_client):
    respx.get(f"{BASE}/arm-profiles").mock(return_value=httpx.Response(200, json=fx("alarm_arm_profiles.json")))
    result = await alarm.list_arm_profiles(mock_client)
    assert [p["name"] for p in result] == ["Away", "Night"]
    assert result[0]["activation_delay_ms"] == 60000
    assert result[0]["record_everything"] is True


@respx.mock
async def test_list_arm_profiles_wrapped_and_empty(mock_client):
    respx.get(f"{BASE}/arm-profiles").mock(
        return_value=httpx.Response(200, json={"data": fx("alarm_arm_profiles.json")}))
    assert len(await alarm.list_arm_profiles(mock_client)) == 2
    mock_client.cache.invalidate("protect_alarm")
    respx.get(f"{BASE}/arm-profiles").mock(return_value=httpx.Response(200, json=[]))
    assert await alarm.list_arm_profiles(mock_client) == []


@respx.mock
async def test_status_disabled_single_object(mock_client):
    respx.get(f"{BASE}/nvrs").mock(return_value=httpx.Response(200, json=fx("alarm_nvr_disarmed.json")))
    result = await alarm.get_alarm_status(mock_client)
    assert result["status"] == "disabled"
    assert result["arm_profile_id"] is None
    assert result["breach_event_count"] == 0


@respx.mock
async def test_status_breach_list_shape(mock_client):
    respx.get(f"{BASE}/nvrs").mock(return_value=httpx.Response(200, json=[fx("alarm_nvr_breach.json")]))
    result = await alarm.get_alarm_status(mock_client)
    assert result["status"] == "breach"
    assert result["arm_profile_id"] == PID
    assert result["breach_event_count"] == 2
    assert result["breach_detected_at"] == 1700000400000


@respx.mock
async def test_status_data_wrapper_and_empty(mock_client):
    route = respx.get(f"{BASE}/nvrs").mock(
        return_value=httpx.Response(200, json={"data": [fx("alarm_nvr_breach.json")]}))
    assert (await alarm.get_alarm_status(mock_client))["status"] == "breach"
    route.mock(return_value=httpx.Response(200, json=[]))
    result = await alarm.get_alarm_status(mock_client)
    assert result["error"] is True and result["category"] == "NOT_FOUND"


def _mock_status(status, profile_id=None):
    nvr = fx("alarm_nvr_disarmed.json")
    mode = {**nvr["armMode"], "status": status, "armProfileId": profile_id}
    respx.get(f"{BASE}/nvrs").mock(return_value=httpx.Response(200, json={**nvr, "armMode": mode}))


@pytest.mark.parametrize("fn,name,status", [
    (alarm.arm_alarm, "arm_alarm", "disabled"), (alarm.disarm_alarm, "disarm_alarm", "armed"),
])
@respx.mock
async def test_arm_disarm_preview_has_impact_and_context(mock_client, fn, name, status):
    _mock_status(status, PID)
    respx.get(f"{BASE}/arm-profiles").mock(
        return_value=httpx.Response(200, json=fx("alarm_arm_profiles.json")))
    post = respx.post(url__regex=r".*/arm-profiles/(enable|disable)")
    result = await fn(mock_client)
    assert result["preview"] is True and result["action"] == name
    assert result["impact"] and result["current_status"] == status
    assert result["active_profile_id"] == PID and not post.called


@respx.mock
async def test_arm_preview_names_active_profile(mock_client):
    _mock_status("disabled", PID)
    profiles = fx("alarm_arm_profiles.json")
    items = profiles if isinstance(profiles, list) else profiles.get("data", [])
    items = [{**items[0], "id": PID}, *items[1:]]
    respx.get(f"{BASE}/arm-profiles").mock(return_value=httpx.Response(200, json=items))
    result = await alarm.arm_alarm(mock_client)
    assert result["active_profile_name"] == items[0]["name"]


@respx.mock
async def test_arm_confirm(mock_client):
    _mock_status("disabled")
    route = respx.post(f"{BASE}/arm-profiles/enable").mock(return_value=httpx.Response(200))
    result = await alarm.arm_alarm(mock_client, confirm=True)
    assert result["executed"] is True and route.called


@respx.mock
async def test_disarm_confirm(mock_client):
    _mock_status("armed")
    route = respx.post(f"{BASE}/arm-profiles/disable").mock(return_value=httpx.Response(200))
    result = await alarm.disarm_alarm(mock_client, confirm=True)
    assert result["executed"] is True and route.called


@respx.mock
@pytest.mark.parametrize("fn,status,confirm", [
    (alarm.arm_alarm, "armed", False), (alarm.arm_alarm, "arming", True),
    (alarm.disarm_alarm, "disabled", False), (alarm.disarm_alarm, "disabled", True),
])
async def test_arm_disarm_noop_when_already_in_state(mock_client, fn, status, confirm):
    _mock_status(status)
    post = respx.post(url__regex=r".*/arm-profiles/(enable|disable)")
    result = await fn(mock_client, confirm=confirm)
    assert result["executed"] is False and "already" in result["message"] and not post.called


@respx.mock
async def test_arm_preview_survives_status_failure(mock_client):
    respx.get(f"{BASE}/nvrs").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE}/arm-profiles").mock(return_value=httpx.Response(500))
    result = await alarm.arm_alarm(mock_client)
    assert result["preview"] is True and "current_status" not in result


@respx.mock
async def test_status_without_arm_mode_is_unavailable(mock_client):
    nvr = {k: v for k, v in fx("alarm_nvr_disarmed.json").items() if k != "armMode"}
    respx.get(f"{BASE}/nvrs").mock(return_value=httpx.Response(200, json=nvr))
    result = await alarm.get_alarm_status(mock_client)
    assert result["error"] is True and result["category"] == "PRODUCT_UNAVAILABLE"


@respx.mock
async def test_status_data_object_wrapper(mock_client):
    nvr = fx("alarm_nvr_disarmed.json")
    respx.get(f"{BASE}/nvrs").mock(return_value=httpx.Response(200, json={"data": nvr}))
    assert (await alarm.get_alarm_status(mock_client))["status"] == "disabled"


def test_id_check_rejects_trailing_newline():
    assert alarm._check_id("abc\n", "x") is not None


@respx.mock
async def test_set_active_profile(mock_client):
    preview = await alarm.set_active_arm_profile(mock_client, PID)
    assert preview["preview"] is True and preview["profile_id"] == PID and preview["impact"]
    route = respx.patch(f"{BASE}/arm-profiles/settings").mock(return_value=httpx.Response(200))
    result = await alarm.set_active_arm_profile(mock_client, PID, confirm=True)
    assert result["executed"] is True
    assert json.loads(route.calls[0].request.content) == {"armProfileId": PID}


@pytest.mark.parametrize("bad", ["", "a/b", "..", "a?b", "a#b", "a b", None, 5])
async def test_id_validation(mock_client, bad):
    for coro in (
        alarm.set_active_arm_profile(mock_client, bad),
        alarm.update_arm_profile(mock_client, bad, {"name": "x"}),
        alarm.delete_arm_profile(mock_client, bad),
        alarm.trigger_alarm_webhook(mock_client, bad),
    ):
        result = await coro
        assert result["error"] is True and result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_create_defaults_preview_and_confirm(mock_client):
    preview = await alarm.create_arm_profile(mock_client, "Home")
    assert preview["preview"] is True
    assert preview["profile"] == {
        "name": "Home", "automations": [], "schedules": [],
        "recordEverything": False, "activationDelay": 0,
    }
    route = respx.post(f"{BASE}/arm-profiles").mock(return_value=httpx.Response(200, json=fx("alarm_arm_profiles.json")[0]))
    result = await alarm.create_arm_profile(
        mock_client, "Home", automations=["b1"],
        schedules=[{"start": "0 0 * * *", "end": "0 6 * * *"}],
        record_everything=True, activation_delay=300000, confirm=True,
    )
    assert result["executed"] is True
    sent = json.loads(route.calls[0].request.content)
    assert sent["activationDelay"] == 300000 and sent["recordEverything"] is True
    assert sent["automations"] == ["b1"]


@pytest.mark.parametrize("kwargs", [
    {"name": ""},
    {"name": "x" * 256},
    {"name": "ok", "automations": "abc"},
    {"name": "ok", "automations": ["a/b"]},
    {"name": "ok", "schedules": [{"start": "0 0 * * *"}]},
    {"name": "ok", "schedules": ["nope"]},
    {"name": "ok", "record_everything": "yes"},
    {"name": "ok", "activation_delay": 5},
    {"name": "ok", "activation_delay": True},
])
async def test_create_validation(mock_client, kwargs):
    result = await alarm.create_arm_profile(mock_client, confirm=True, **kwargs)
    assert result["error"] is True and result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_update_preview_confirm_and_aliases(mock_client):
    preview = await alarm.update_arm_profile(mock_client, PID, {"record_everything": True})
    assert preview["preview"] is True and preview["updates"] == {"recordEverything": True}
    route = respx.patch(f"{BASE}/arm-profiles/{PID}").mock(
        return_value=httpx.Response(200, json=fx("alarm_arm_profiles.json")[0]))
    result = await alarm.update_arm_profile(mock_client, PID, {"activationDelay": 600000}, confirm=True)
    assert result["executed"] is True
    assert json.loads(route.calls[0].request.content) == {"activationDelay": 600000}


@respx.mock
async def test_update_empty_response_is_silent_noop(mock_client):
    respx.patch(f"{BASE}/arm-profiles/{PID}").mock(return_value=httpx.Response(200, json={}))
    result = await alarm.update_arm_profile(mock_client, PID, {"name": "New"}, confirm=True)
    assert result["executed"] is False and "empty body" in result["message"]


async def test_update_validation(mock_client):
    for updates in ({}, "x", {"bogus": 1}, {"activationDelay": 7}):
        result = await alarm.update_arm_profile(mock_client, PID, updates)
        assert result["category"] == "VALIDATION_ERROR"


async def test_update_does_not_mutate_input(mock_client):
    updates = {"record_everything": True}
    await alarm.update_arm_profile(mock_client, PID, updates)
    assert updates == {"record_everything": True}


@respx.mock
async def test_delete_preview_and_confirm(mock_client):
    preview = await alarm.delete_arm_profile(mock_client, PID)
    assert preview["preview"] is True and "irreversible" in preview["message"]
    route = respx.delete(f"{BASE}/arm-profiles/{PID}").mock(return_value=httpx.Response(200))
    result = await alarm.delete_arm_profile(mock_client, PID, confirm=True)
    assert result["executed"] is True and route.called


@respx.mock
async def test_webhook_preview_confirm_not_found(mock_client):
    preview = await alarm.trigger_alarm_webhook(mock_client, "hook1")
    assert preview["preview"] is True and preview["impact"]
    route = respx.post(f"{BASE}/alarm-manager/webhook/hook1").mock(return_value=httpx.Response(200))
    assert (await alarm.trigger_alarm_webhook(mock_client, "hook1", confirm=True))["executed"] is True
    route.mock(return_value=httpx.Response(404, json={"error": "nf"}))
    result = await alarm.trigger_alarm_webhook(mock_client, "hook1", confirm=True)
    assert result["category"] == "NOT_FOUND"


@respx.mock
async def test_webhook_other_errors_propagate(mock_client):
    from unifi_mcp.errors import UnifiError
    respx.post(f"{BASE}/alarm-manager/webhook/hook1").mock(return_value=httpx.Response(403))
    with pytest.raises(UnifiError):
        await alarm.trigger_alarm_webhook(mock_client, "hook1", confirm=True)
