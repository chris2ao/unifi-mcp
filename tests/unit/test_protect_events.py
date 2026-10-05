"""Tests for Protect live event streaming (WebSocket mocked)."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx
import websockets

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.protect import events as ev

FIXTURES = Path(__file__).parent.parent / "fixtures" / "protect"
CAM1 = "000000000000000000000c01"
CAM2 = "000000000000000000000c02"
CAMS_URL = "https://192.168.1.1/proxy/protect/integration/v1/cameras"


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


class FakeWS:
    def __init__(self, messages, hang=True):
        self._messages = list(messages)
        self._hang = hang

    async def recv(self):
        if self._messages:
            m = self._messages.pop(0)
            return m if isinstance(m, str) else json.dumps(m)
        if self._hang:
            await asyncio.sleep(60)
        raise websockets.exceptions.ConnectionClosedOK(None, None)


class FakeConnect:
    last = None

    def __init__(self, messages, hang=True, error=None):
        self.messages, self.hang, self.error = messages, hang, error

    def __call__(self, url, **kwargs):
        FakeConnect.last = {"url": url, **kwargs}
        return self

    async def __aenter__(self):
        if self.error:
            raise self.error
        return FakeWS(self.messages, self.hang)

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def cams():
    with respx.mock:
        respx.get(CAMS_URL).mock(return_value=httpx.Response(
            200, json=[{"id": CAM1, "name": "Driveway Cam"}, {"id": CAM2, "name": "Yard Cam"}]))
        yield


def patch_ws(monkeypatch, messages, **kw):
    fake = FakeConnect(messages, **kw)
    monkeypatch.setattr(ev.websockets, "connect", fake)
    return fake


def test_ws_url_and_ssl():
    assert ev._ws_url("https://10.0.0.1", "events") == (
        "wss://10.0.0.1/proxy/protect/integration/v1/subscribe/events")
    assert ev._ws_url("http://10.0.0.1/", "devices").startswith("ws://10.0.0.1/proxy")
    assert ev._ws_url("10.0.0.1", "events").startswith("wss://10.0.0.1/")
    assert ev._ssl_context("ws://x", True) is None
    assert ev._ssl_context("wss://x", False).verify_mode.name == "CERT_NONE"
    assert ev._ssl_context("wss://x", True).verify_mode.name == "CERT_REQUIRED"


def test_iso():
    assert ev._iso(1741267544209) == "2025-03-06T13:25:44.209000Z"
    assert ev._iso(None) is None
    assert ev._iso(True) is None
    assert ev._iso(1e30) is None


@pytest.mark.asyncio
async def test_watch_events_all(mock_client, monkeypatch, cams):
    fake = patch_ws(monkeypatch, load("events_messages.json"))
    result = await ev.watch_protect_events(mock_client, seconds=0.3)
    assert result["count"] == 6  # e01 add+update merge into one event
    assert result["messages_seen"] == 7
    first = result["events"][0]
    assert first["event_type"] == "motion"
    assert first["camera_name"] == "Driveway Cam"
    assert first["start"].endswith("Z") and first["end"] is not None
    person = [e for e in result["events"] if e["smart_detect_types"] == ["person"]][0]
    assert person["score"] == 87
    assert "no REST event history" in result["note"] or "no REST" in result["note"]
    # connection details: wss URL, API key header, ssl default (verify False)
    assert fake.last["url"].startswith("wss://192.168.1.1/proxy/protect/integration/v1/subscribe/events")
    assert fake.last["additional_headers"] == {"X-API-Key": "test-key"}
    assert fake.last["ssl"].check_hostname is False


@pytest.mark.asyncio
async def test_watch_events_filters(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.watch_protect_events(mock_client, seconds=0.2, event_types=["ring"])
    assert [e["event_type"] for e in r["events"]] == ["ring"]
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.watch_protect_events(mock_client, seconds=0.2, camera_id=CAM2)
    assert r["count"] == 1 and r["events"][0]["camera_name"] == "Yard Cam"


@pytest.mark.asyncio
async def test_watch_events_max_events_stops_early(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.watch_protect_events(mock_client, seconds=5, max_events=2)
    assert r["messages_seen"] == 2 and r["count"] == 1  # max_events caps messages


@pytest.mark.asyncio
async def test_watch_events_caps(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, [], hang=False)
    r = await ev.watch_protect_events(mock_client, seconds=9999, max_events=9999)
    assert r["window_seconds"] == 120 and r["capped"] is True
    assert r["count"] == 0


@pytest.mark.asyncio
async def test_watch_events_skips_bad_messages(mock_client, monkeypatch, cams):
    msgs = ["not json", "[1,2]", {"type": "add"}, {"type": "add", "item": {"type": "motion", "device": CAM1, "start": 1741267544209}}]
    patch_ws(monkeypatch, msgs, hang=False)
    r = await ev.watch_protect_events(mock_client, seconds=1)
    assert r["messages_seen"] == 4 and r["count"] == 1


@pytest.mark.asyncio
async def test_watch_events_validation(mock_client):
    for kwargs in ({"seconds": 0}, {"seconds": "x"}, {"max_events": -1}, {"camera_id": "a/b"},
                   {"event_types": "motion"}, {"event_types": [1]}):
        r = await ev.watch_protect_events(mock_client, **kwargs)
        assert r["error"] is True and r["category"] == "VALIDATION_ERROR", kwargs


@pytest.mark.asyncio
async def test_watch_events_connection_error(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, [], error=OSError("refused"))
    r = await ev.watch_protect_events(mock_client, seconds=1)
    assert r["error"] is True and r["category"] == "CONNECTION_ERROR"
    assert "test-key" not in r["message"]


@pytest.mark.asyncio
async def test_camera_name_lookup_failure_is_reported(mock_client, monkeypatch):
    patch_ws(monkeypatch, load("events_messages.json")[:1], hang=False)
    with respx.mock:
        respx.get(CAMS_URL).mock(return_value=httpx.Response(403, json={}))
        r = await ev.watch_protect_events(mock_client, seconds=1)
    assert r["count"] == 1 and r["events"][0]["camera_name"] is None
    assert "Camera names unavailable" in r["warning"]


@pytest.mark.asyncio
async def test_list_motion_events(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.list_motion_events(mock_client, seconds=0.2)
    assert r["tool"] == "list_motion_events"
    assert {e["event_type"] for e in r["events"]} == {"motion"}
    assert r["count"] == 2  # e01 add+update is one event, plus e04
    merged = [e for e in r["events"] if e["event_id"].endswith("e01") or e["event_id"] == r["events"][0]["event_id"]][0]
    assert merged["start"] is not None and merged["end"] is not None


@pytest.mark.asyncio
async def test_list_motion_events_camera(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.list_motion_events(mock_client, seconds=0.2, camera_id=CAM2)
    assert r["count"] == 1


@pytest.mark.asyncio
async def test_list_smart_detections(mock_client, monkeypatch, cams):
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.list_smart_detections(mock_client, seconds=0.2)
    assert {e["event_type"] for e in r["events"]} == {
        "smartDetectZone", "smartDetectLine", "smartAudioDetect"}
    patch_ws(monkeypatch, load("events_messages.json"))
    r = await ev.list_smart_detections(mock_client, seconds=0.2, detect_types=["vehicle"])
    assert r["count"] == 1 and r["events"][0]["event_type"] == "smartDetectLine"


@pytest.mark.asyncio
async def test_watch_device_updates(mock_client, monkeypatch):
    fake = patch_ws(monkeypatch, load("events_device_messages.json"))
    r = await ev.watch_protect_device_updates(mock_client, seconds=0.2)
    assert r["count"] == 4
    assert fake.last["url"].endswith("/subscribe/devices")
    assert [m["message_type"] for m in r["messages"]] == ["update", "add", "remove", "update"]
    assert r["messages"][0]["changed_fields"] == ["name", "state"]
    assert r["messages"][3]["device_ids"] == [CAM1, CAM2]
    assert r["messages"][3]["changed_fields"] == ["isMicEnabled"]


@pytest.mark.asyncio
async def test_watch_device_updates_errors(mock_client, monkeypatch):
    r = await ev.watch_protect_device_updates(mock_client, seconds=0)
    assert r["category"] == "VALIDATION_ERROR"
    r = await ev.watch_protect_device_updates(mock_client, max_messages="x")
    assert r["category"] == "VALIDATION_ERROR"
    patch_ws(monkeypatch, [], error=websockets.exceptions.InvalidHandshake("bad"))
    r = await ev.watch_protect_device_updates(mock_client, seconds=1)
    assert r["category"] == "CONNECTION_ERROR"
    patch_ws(monkeypatch, [{"type": "add"}], hang=False)
    r = await ev.watch_protect_device_updates(mock_client, seconds=1)
    assert r["count"] == 0 and r["messages_seen"] == 1


def test_module_conventions():
    assert ev.GROUP == "cameras"
    assert ev.TIER2_TOOLS == {}
    assert len(ev.TOOLS) == 4
    assert "LIVE" in ev.list_motion_events.__doc__
    assert "no REST" in ev.list_smart_detections.__doc__ or "no REST" in ev.list_smart_detections.__doc__.replace("\n", " ")
    assert "—" not in Path(ev.__file__).read_text()
