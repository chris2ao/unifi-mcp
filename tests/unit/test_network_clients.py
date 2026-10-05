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
async def test_list_clients(mock_client):
    from unifi_mcp.tools.network.clients import list_clients

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_clients(mock_client)
    assert len(result) == 3
    assert result[0]["hostname"] == "MacBook-Pro"
    assert result[0]["ip"] == "192.168.1.100"
    assert "uptime_human" in result[0]
    assert "tx_human" in result[0]


@respx.mock
@pytest.mark.asyncio
async def test_get_client(mock_client):
    from unifi_mcp.tools.network.clients import get_client

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta/AA:BB:CC:DD:EE:01").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][0]]})
    )
    result = await get_client(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert result["hostname"] == "MacBook-Pro"
    assert result["mac"] == "AA:BB:CC:DD:EE:01"


@respx.mock
@pytest.mark.asyncio
async def test_block_client_preview(mock_client):
    from unifi_mcp.tools.network.clients import block_client

    result = await block_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "block_client"
    assert "confirm=True" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_block_client_confirmed(mock_client):
    from unifi_mcp.tools.network.clients import block_client

    respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await block_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_unblock_client_preview(mock_client):
    from unifi_mcp.tools.network.clients import unblock_client

    result = await unblock_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "unblock_client"


@respx.mock
@pytest.mark.asyncio
async def test_reconnect_client(mock_client):
    from unifi_mcp.tools.network.clients import reconnect_client

    respx.post("https://192.168.1.1/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await reconnect_client(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert result["action"] == "reconnect_client"


@respx.mock
@pytest.mark.asyncio
async def test_set_client_alias(mock_client):
    from unifi_mcp.tools.network.clients import set_client_alias

    respx.put("https://192.168.1.1/proxy/network/api/s/default/rest/user/cli001").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "cli001", "name": "My Laptop"}]})
    )
    result = await set_client_alias(mock_client, client_id="cli001", name="My Laptop")
    assert result["data"][0]["name"] == "My Laptop"


@respx.mock
@pytest.mark.asyncio
async def test_list_all_clients(mock_client):
    from unifi_mcp.tools.network.clients import list_all_clients

    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/user").mock(
        return_value=httpx.Response(200, json={
            "meta": {"rc": "ok"},
            "data": [
                {"_id": "u1", "mac": "AA:BB:CC:DD:EE:01", "hostname": "MacBook-Pro", "name": "Chris Laptop"},
                {"_id": "u2", "mac": "AA:BB:CC:DD:EE:04", "hostname": "old-device", "name": ""}
            ]
        })
    )
    result = await list_all_clients(mock_client)
    assert len(result) == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_client_history(mock_client):
    from unifi_mcp.tools.network.clients import get_client_history

    route = respx.post("https://192.168.1.1/proxy/network/api/s/default/stat/report/hourly.user").mock(
        return_value=httpx.Response(200, json={
            "meta": {"rc": "ok"},
            "data": [
                {"time": 1713100000000, "rx_bytes": 1024, "tx_bytes": 2048}
            ]
        })
    )
    result = await get_client_history(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert len(result) == 1
    assert result[0]["time"] == 1713100000000
    assert result[0]["rx_bytes"] == 1024

    # Request must ask for the `time` attr and a bounded range so buckets are timestamped.
    body = json.loads(route.calls.last.request.content)
    assert body["attrs"] == ["time", "rx_bytes", "tx_bytes"]
    assert body["mac"] == "AA:BB:CC:DD:EE:01"
    assert isinstance(body["start"], int) and isinstance(body["end"], int)
    assert body["end"] > body["start"]


@respx.mock
@pytest.mark.asyncio
async def test_get_client_history_explicit_range(mock_client):
    from unifi_mcp.tools.network.clients import get_client_history

    route = respx.post("https://192.168.1.1/proxy/network/api/s/default/stat/report/hourly.user").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    await get_client_history(mock_client, mac="AA:BB:CC:DD:EE:01", start=1000, end=2000)
    body = json.loads(route.calls.last.request.content)
    assert body["start"] == 1000
    assert body["end"] == 2000


@respx.mock
@pytest.mark.asyncio
async def test_get_client_history_daily_interval(mock_client):
    from unifi_mcp.tools.network.clients import get_client_history

    route = respx.post("https://192.168.1.1/proxy/network/api/s/default/stat/report/daily.user").mock(
        return_value=httpx.Response(
            200, json={"meta": {"rc": "ok"}, "data": [{"time": 1_717_000_000_000, "rx_bytes": 5, "tx_bytes": 6}]}
        )
    )
    result = await get_client_history(mock_client, mac="AA:BB:CC:DD:EE:01", interval="daily")
    assert result[0]["rx_bytes"] == 5
    assert route.called  # daily.user endpoint was hit


@respx.mock
@pytest.mark.asyncio
async def test_get_client_history_unknown_interval_falls_back_to_hourly(mock_client):
    from unifi_mcp.tools.network.clients import get_client_history

    route = respx.post("https://192.168.1.1/proxy/network/api/s/default/stat/report/hourly.user").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    await get_client_history(mock_client, mac="AA:BB:CC:DD:EE:01", interval="bogus")
    assert route.called  # bogus interval routed to hourly.user


def test_clients_tools_list():
    from unifi_mcp.tools.network.clients import TOOLS
    assert len(TOOLS) == 12


# ---------------------------------------------------------------------------
# v0.8.0: official-API client lookup, guest authorize/unauthorize, recent clients
# ---------------------------------------------------------------------------

SITE_UUID = "00000000-0000-0000-0000-000000000001"
BASE = "https://192.168.1.1"
V1 = f"{BASE}/proxy/network/integration/v1/sites/{SITE_UUID}/clients"
HISTORY = f"{BASE}/proxy/network/v2/api/site/default/clients/history"
GUEST_ID = "00000000-0000-0000-0000-0000000000a1"
DEFAULT_ID = "00000000-0000-0000-0000-0000000000a2"


@pytest.fixture
def v1_client(mock_client):
    mock_client._site_id = SITE_UUID
    return mock_client


def _guest_detail():
    return load_fixture("clients_v1_detail_guest.json")


def _authorized_guest():
    detail = _guest_detail()
    return {**detail, "access": {**detail["access"], "authorized": True}}


def test_clients_tier2_declaration():
    from unifi_mcp.tools.network import clients

    assert clients.TIER2_TOOLS == {
        "block_client": "clients", "unblock_client": "clients",
        "authorize_guest": "clients", "unauthorize_guest": "clients",
    }
    names = {t.__name__ for t in clients.TOOLS}
    assert {"list_recent_clients", "get_client_v1", "authorize_guest", "unauthorize_guest"} <= names


@respx.mock
@pytest.mark.asyncio
async def test_get_client_v1_by_id(v1_client):
    from unifi_mcp.tools.network.clients import get_client_v1

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_guest_detail()))
    result = await get_client_v1(v1_client, GUEST_ID)
    assert result["name"] == "Guest Phone"
    assert result["access_type"] == "GUEST"
    assert result["authorized"] is False
    assert result["mac"] == "aa:bb:cc:00:00:01"
    assert "details" not in result


@respx.mock
@pytest.mark.asyncio
async def test_get_client_v1_by_mac_uses_filter(v1_client):
    from unifi_mcp.tools.network.clients import get_client_v1

    fixture = load_fixture("clients_v1_list.json")
    route = respx.get(V1).mock(
        return_value=httpx.Response(200, json={**fixture, "data": fixture["data"][:1]})
    )
    result = await get_client_v1(v1_client, "AA-BB-CC-00-00-01")
    assert result["id"] == GUEST_ID
    request = route.calls.last.request
    assert request.url.params["filter"] == "macAddress.eq('aa:bb:cc:00:00:01')"


@respx.mock
@pytest.mark.asyncio
async def test_get_client_v1_extra_fields_go_to_details(v1_client):
    from unifi_mcp.tools.network.clients import get_client_v1

    detail = {**_guest_detail(), "ssid": "Guest WiFi"}
    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=detail))
    result = await get_client_v1(v1_client, GUEST_ID)
    assert result["details"] == {"ssid": "Guest WiFi"}


@respx.mock
@pytest.mark.asyncio
async def test_get_client_v1_not_found_by_id_and_mac(v1_client):
    from unifi_mcp.tools.network.clients import get_client_v1

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(404, json={}))
    by_id = await get_client_v1(v1_client, GUEST_ID)
    assert by_id["error"] is True and by_id["category"] == "NOT_FOUND"

    respx.get(V1).mock(return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    by_mac = await get_client_v1(v1_client, "aa:bb:cc:00:00:99")
    assert by_mac["category"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a b", "x?y", None, 5])
async def test_get_client_v1_rejects_bad_ref(v1_client, bad):
    from unifi_mcp.tools.network.clients import get_client_v1

    result = await get_client_v1(v1_client, bad)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_get_client_v1_connection_error_is_structured(v1_client):
    from unifi_mcp.tools.network.clients import get_client_v1

    respx.get(f"{V1}/{GUEST_ID}").mock(side_effect=httpx.ConnectError("boom"))
    result = await get_client_v1(v1_client, GUEST_ID)
    assert result["category"] == "CONNECTION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_preview_makes_no_write(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_guest_detail()))
    post = respx.post(f"{V1}/{GUEST_ID}/actions").mock(return_value=httpx.Response(200, json={}))
    result = await authorize_guest(v1_client, GUEST_ID, minutes=60, data_limit_mb=500)
    assert result["preview"] is True
    assert result["action"] == "authorize_guest"
    assert result["request"] == {
        "action": "AUTHORIZE_GUEST_ACCESS", "timeLimitMinutes": 60, "dataUsageLimitMBytes": 500,
    }
    assert result["client"]["name"] == "Guest Phone"
    assert post.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_preview_is_deterministic(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_guest_detail()))
    first = await authorize_guest(v1_client, GUEST_ID, minutes=30)
    second = await authorize_guest(v1_client, GUEST_ID, minutes=30)
    assert first == second


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_confirm_executes_and_invalidates(v1_client):
    import json as _json
    from unifi_mcp.tools.network.clients import authorize_guest

    v1_client.cache.set("clients:stale", {"x": 1}, 60.0)
    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_guest_detail()))
    post = respx.post(f"{V1}/{GUEST_ID}/actions").mock(
        return_value=httpx.Response(200, json=load_fixture("clients_action_authorize.json"))
    )
    result = await authorize_guest(
        v1_client, GUEST_ID, minutes=60, data_limit_mb=500, rx_kbps=5000, tx_kbps=1000, confirm=True,
    )
    assert result["executed"] is True
    assert result["response"]["grantedAuthorization"]["authorizationMethod"] == "API"
    assert _json.loads(post.calls.last.request.content) == {
        "action": "AUTHORIZE_GUEST_ACCESS", "timeLimitMinutes": 60, "dataUsageLimitMBytes": 500,
        "rxRateLimitKbps": 5000, "txRateLimitKbps": 1000,
    }
    assert v1_client.cache.get("clients:stale") is None


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_by_mac(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    fixture = load_fixture("clients_v1_list.json")
    respx.get(V1).mock(return_value=httpx.Response(200, json={**fixture, "data": fixture["data"][:1]}))
    post = respx.post(f"{V1}/{GUEST_ID}/actions").mock(
        return_value=httpx.Response(200, json=load_fixture("clients_action_authorize.json"))
    )
    result = await authorize_guest(v1_client, "aa:bb:cc:00:00:01", confirm=True)
    assert result["executed"] is True
    assert post.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_empty_response_is_not_executed(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_guest_detail()))
    respx.post(f"{V1}/{GUEST_ID}/actions").mock(return_value=httpx.Response(200, json={}))
    result = await authorize_guest(v1_client, GUEST_ID, confirm=True)
    assert result["executed"] is False
    assert "Verify" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_rejects_non_guest(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{DEFAULT_ID}").mock(
        return_value=httpx.Response(200, json=load_fixture("clients_v1_detail_default.json"))
    )
    result = await authorize_guest(v1_client, DEFAULT_ID, confirm=True)
    assert result["category"] == "VALIDATION_ERROR"
    assert "not a guest" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_not_found(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(404, json={}))
    result = await authorize_guest(v1_client, GUEST_ID)
    assert result["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_lookup_connection_error(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(side_effect=httpx.ConnectError("boom"))
    result = await authorize_guest(v1_client, GUEST_ID)
    assert result["category"] == "CONNECTION_ERROR"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"minutes": 0}, {"minutes": 1_000_001}, {"minutes": True}, {"minutes": 1.5},
        {"data_limit_mb": 0}, {"data_limit_mb": 2_000_000},
        {"rx_kbps": 1}, {"rx_kbps": 100_001}, {"tx_kbps": 1}, {"tx_kbps": "fast"},
    ],
)
async def test_authorize_guest_validates_limits_before_any_call(v1_client, kwargs):
    from unifi_mcp.tools.network.clients import authorize_guest

    result = await authorize_guest(v1_client, GUEST_ID, **kwargs)
    assert result["category"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_authorize_guest_rejects_bad_ref(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    result = await authorize_guest(v1_client, "../etc")
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_unauthorize_guest_preview_has_impact(v1_client):
    from unifi_mcp.tools.network.clients import unauthorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_authorized_guest()))
    post = respx.post(f"{V1}/{GUEST_ID}/actions").mock(return_value=httpx.Response(200, json={}))
    result = await unauthorize_guest(v1_client, GUEST_ID)
    assert result["preview"] is True
    assert "disconnected" in result["impact"]
    assert post.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_unauthorize_guest_confirm(v1_client):
    import json as _json
    from unifi_mcp.tools.network.clients import unauthorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_authorized_guest()))
    post = respx.post(f"{V1}/{GUEST_ID}/actions").mock(
        return_value=httpx.Response(200, json=load_fixture("clients_action_unauthorize.json"))
    )
    result = await unauthorize_guest(v1_client, GUEST_ID, confirm=True)
    assert result["executed"] is True
    assert _json.loads(post.calls.last.request.content) == {"action": "UNAUTHORIZE_GUEST_ACCESS"}


@respx.mock
@pytest.mark.asyncio
async def test_unauthorize_guest_empty_response_not_executed(v1_client):
    from unifi_mcp.tools.network.clients import unauthorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_authorized_guest()))
    respx.post(f"{V1}/{GUEST_ID}/actions").mock(return_value=httpx.Response(200, json={}))
    result = await unauthorize_guest(v1_client, GUEST_ID, confirm=True)
    assert result["executed"] is False


@pytest.mark.asyncio
async def test_unauthorize_guest_rejects_bad_ref(v1_client):
    from unifi_mcp.tools.network.clients import unauthorize_guest

    assert (await unauthorize_guest(v1_client, "a b"))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_unauthorize_guest_non_guest_rejected(v1_client):
    from unifi_mcp.tools.network.clients import unauthorize_guest

    respx.get(f"{V1}/{DEFAULT_ID}").mock(
        return_value=httpx.Response(200, json=load_fixture("clients_v1_detail_default.json"))
    )
    result = await unauthorize_guest(v1_client, DEFAULT_ID)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_list_recent_clients_sorted_newest_first(v1_client):
    from unifi_mcp.tools.network.clients import list_recent_clients

    route = respx.get(HISTORY).mock(
        return_value=httpx.Response(200, json=load_fixture("clients_history.json"))
    )
    result = await list_recent_clients(v1_client)
    assert [c["mac"] for c in result] == [
        "aa:bb:cc:00:00:04", "aa:bb:cc:00:00:03", "aa:bb:cc:00:00:05",
    ]
    tablet = result[1]
    assert tablet["name"] == "Old Tablet"
    assert tablet["last_ip"] == "192.0.2.60"
    assert tablet["last_network"] == "Main LAN"
    assert tablet["last_uplink_name"] == "Office AP"
    assert result[0]["name"] == "printer"
    assert route.calls.last.request.url.params["withinHours"] == "0"


@respx.mock
@pytest.mark.asyncio
async def test_list_recent_clients_limit_and_hours(v1_client):
    from unifi_mcp.tools.network.clients import list_recent_clients

    route = respx.get(HISTORY).mock(
        return_value=httpx.Response(200, json=load_fixture("clients_history.json"))
    )
    result = await list_recent_clients(v1_client, limit=1, hours=24)
    assert len(result) == 1
    assert route.calls.last.request.url.params["withinHours"] == "24"


@respx.mock
@pytest.mark.asyncio
async def test_list_recent_clients_shape_variance(v1_client):
    from unifi_mcp.tools.network.clients import list_recent_clients

    rows = load_fixture("clients_history.json")
    respx.get(HISTORY).mock(return_value=httpx.Response(200, json={"data": rows}))
    assert len(await list_recent_clients(v1_client)) == 3
    v1_client.cache.invalidate("clients")
    respx.get(HISTORY).mock(return_value=httpx.Response(200, json={"data": None}))
    assert await list_recent_clients(v1_client) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 1001}, {"hours": 0}, {"hours": 9000}, {"limit": "x"}])
async def test_list_recent_clients_validation(v1_client, kwargs):
    from unifi_mcp.tools.network.clients import list_recent_clients

    result = await list_recent_clients(v1_client, **kwargs)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_unauthorize_guest_not_authorized_is_not_previewed(v1_client):
    from unifi_mcp.tools.network.clients import unauthorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_guest_detail()))
    post = respx.post(f"{V1}/{GUEST_ID}/actions").mock(return_value=httpx.Response(200, json={}))
    result = await unauthorize_guest(v1_client, GUEST_ID)
    assert result["executed"] is False and "preview" not in result
    assert "not currently authorized" in result["message"]
    assert post.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_authorize_guest_preview_notes_existing_authorization(v1_client):
    from unifi_mcp.tools.network.clients import authorize_guest

    respx.get(f"{V1}/{GUEST_ID}").mock(return_value=httpx.Response(200, json=_authorized_guest()))
    result = await authorize_guest(v1_client, GUEST_ID)
    assert result["preview"] is True
    assert "already authorized" in result["impact"]


@respx.mock
@pytest.mark.asyncio
async def test_find_client_by_mac_rejects_mismatched_result(v1_client):
    from unifi_mcp.tools.network.clients import get_client_v1

    fixture = load_fixture("clients_v1_list.json")
    other = {**fixture["data"][0], "macAddress": "de:ad:be:ef:00:99"}
    respx.get(V1).mock(return_value=httpx.Response(200, json={**fixture, "data": [other]}))
    result = await get_client_v1(v1_client, "AA-BB-CC-00-00-01")
    assert result["error"] is True and result["category"] == "NOT_FOUND"
