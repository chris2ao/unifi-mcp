import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig

FIXTURES = Path(__file__).parent.parent / "fixtures"
SITE_UUID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    client = UnifiClient(config, TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())

from unifi_mcp.tools.network import traffic_matching_lists as tm

BASE = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/traffic-matching-lists"
P_ID = "00000000-0000-0000-0000-0000000000b1"


def test_module_declarations():
    assert tm.GROUP == "security"
    assert tm.TIER2_TOOLS == {
        "create_traffic_matching_list": "zbf",
        "update_traffic_matching_list": "zbf",
        "delete_traffic_matching_list": "zbf",
    }
    assert len(tm.TOOLS) == 5


@respx.mock
async def test_list_all_and_by_type(mock_client):
    respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists.json")))
    assert len(await tm.list_traffic_matching_lists(mock_client)) == 3
    ports = await tm.list_traffic_matching_lists(mock_client, type="PORTS")
    assert [p["name"] for p in ports] == ["Web ports"]
    assert ports[0]["items"][0] == {"type": "PORT_NUMBER", "value": 80}


@respx.mock
async def test_list_empty_and_bare_list(mock_client):
    respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_empty.json")))
    assert await tm.list_traffic_matching_lists(mock_client) == []
    mock_client.cache.invalidate("zbf")
    respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists.json")["data"]))
    assert len(await tm.list_traffic_matching_lists(mock_client, type="IPV6_ADDRESSES")) == 1


async def test_list_invalid_type(mock_client):
    assert (await tm.list_traffic_matching_lists(mock_client, type="X"))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_get(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_ports.json")))
    result = await tm.get_traffic_matching_list(mock_client, P_ID)
    assert result["type"] == "PORTS" and len(result["items"]) == 3


@respx.mock
async def test_get_wrapped_and_not_found(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(
        return_value=httpx.Response(200, json={"data": [load_fixture("traffic_matching_lists_ports.json")]}))
    assert (await tm.get_traffic_matching_list(mock_client, P_ID))["id"] == P_ID
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(404, json={}))
    result = await tm.get_traffic_matching_list(mock_client, P_ID)
    assert result["category"] == "NOT_FOUND" and result["list_id"] == P_ID


@respx.mock
async def test_get_empty_data_and_other_error(mock_client):
    from unifi_mcp.errors import UnifiError
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await tm.get_traffic_matching_list(mock_client, P_ID))["category"] == "NOT_FOUND"
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(403, json={}))
    with pytest.raises(UnifiError):
        await tm.get_traffic_matching_list(mock_client, P_ID)


@pytest.mark.parametrize("bad", ["", "a/b", "..", "x?y", "a b"])
async def test_id_validation(mock_client, bad):
    for result in (
        await tm.get_traffic_matching_list(mock_client, bad),
        await tm.delete_traffic_matching_list(mock_client, bad),
        await tm.update_traffic_matching_list(mock_client, bad, name="x"),
    ):
        assert result["category"] == "VALIDATION_ERROR"


# ---- normalization ----

@pytest.mark.parametrize("list_type,items,expected", [
    ("PORTS", [80, "443", "8000-8100", {"type": "PORT_NUMBER", "value": 22},
               {"type": "PORT_NUMBER_RANGE", "start": 1, "stop": 65535}],
     [{"type": "PORT_NUMBER", "value": 80}, {"type": "PORT_NUMBER", "value": 443},
      {"type": "PORT_NUMBER_RANGE", "start": 8000, "stop": 8100},
      {"type": "PORT_NUMBER", "value": 22}, {"type": "PORT_NUMBER_RANGE", "start": 1, "stop": 65535}]),
    ("IPV4_ADDRESSES", ["192.0.2.5", "198.51.100.0/24", "10.0.0.10-10.0.0.20",
                        {"type": "IP_ADDRESS", "value": "192.0.2.6"}],
     [{"type": "IP_ADDRESS", "value": "192.0.2.5"}, {"type": "SUBNET", "value": "198.51.100.0/24"},
      {"type": "IP_ADDRESS_RANGE", "start": "10.0.0.10", "stop": "10.0.0.20"},
      {"type": "IP_ADDRESS", "value": "192.0.2.6"}]),
    ("IPV6_ADDRESSES", ["2001:db8::1", "2001:db8:1::/64"],
     [{"type": "IP_ADDRESS", "value": "2001:db8::1"}, {"type": "SUBNET", "value": "2001:db8:1::/64"}]),
])
def test_normalize_ok(list_type, items, expected):
    normalized, err = tm.normalize_items(list_type, items)
    assert err is None and normalized == expected


@pytest.mark.parametrize("list_type,items", [
    ("PORTS", []), ("PORTS", None), ("PORTS", "80"),
    ("PORTS", [0]), ("PORTS", [65536]), ("PORTS", [True]), ("PORTS", ["abc"]), ("PORTS", [1.5]),
    ("PORTS", ["100-50"]), ("PORTS", ["0-10"]), ("PORTS", ["1-70000"]),
    ("PORTS", [{"type": "BOGUS", "value": 1}]), ("PORTS", [{"type": "PORT_NUMBER"}]),
    ("PORTS", [{"type": "PORT_NUMBER_RANGE", "start": 1}]),
    ("IPV4_ADDRESSES", ["999.0.0.1"]), ("IPV4_ADDRESSES", ["2001:db8::1"]),
    ("IPV4_ADDRESSES", ["198.51.100.5/24"]),           # host bits set
    ("IPV4_ADDRESSES", ["198.51.100.0/33"]),
    ("IPV4_ADDRESSES", ["10.0.0.20-10.0.0.10"]),       # reversed
    ("IPV4_ADDRESSES", ["10.0.0.1-2001:db8::1"]),
    ("IPV4_ADDRESSES", [5]),
    ("IPV4_ADDRESSES", [{"type": "SUBNET", "value": "2001:db8::/64"}]),
    ("IPV4_ADDRESSES", [{"type": "IP_ADDRESS", "value": 5}]),
    ("IPV6_ADDRESSES", ["192.0.2.1"]), ("IPV6_ADDRESSES", ["2001:db8::1-2001:db8::5"]),
    ("IPV6_ADDRESSES", ["2001:db8:1::5/64"]),
    ("IPV6_ADDRESSES", [{"type": "IP_ADDRESS_RANGE", "start": "2001:db8::1", "stop": "2001:db8::2"}]),
])
def test_normalize_errors(list_type, items):
    normalized, err = tm.normalize_items(list_type, items)
    assert normalized is None and err["category"] == "VALIDATION_ERROR"


# ---- create ----

@respx.mock
async def test_create_preview(mock_client):
    result = await tm.create_traffic_matching_list(mock_client, " Web ", "PORTS", [80, "8000-8100"])
    assert result["preview"] is True and result["action"] == "create_traffic_matching_list"
    assert result["list"] == {"type": "PORTS", "name": "Web", "items": [
        {"type": "PORT_NUMBER", "value": 80}, {"type": "PORT_NUMBER_RANGE", "start": 8000, "stop": 8100}]}
    assert len(respx.calls) == 0
    assert await tm.create_traffic_matching_list(mock_client, " Web ", "PORTS", [80, "8000-8100"]) == result


@respx.mock
async def test_create_confirmed(mock_client):
    route = respx.post(BASE).mock(return_value=httpx.Response(201, json={"id": P_ID, "type": "IPV4_ADDRESSES"}))
    mock_client.cache.set("zbf:k", {"x": 1}, 60.0)
    items = ["192.0.2.5"]
    result = await tm.create_traffic_matching_list(mock_client, "Hosts", "IPV4_ADDRESSES", items, confirm=True)
    assert result["executed"] is True
    assert json.loads(route.calls[0].request.content) == {
        "type": "IPV4_ADDRESSES", "name": "Hosts", "items": [{"type": "IP_ADDRESS", "value": "192.0.2.5"}]}
    assert items == ["192.0.2.5"]
    assert mock_client.cache.get("zbf:k") is None


@respx.mock
async def test_create_silent_noop(mock_client):
    respx.post(BASE).mock(return_value=httpx.Response(200, json={}))
    result = await tm.create_traffic_matching_list(mock_client, "x", "PORTS", [1], confirm=True)
    assert result["executed"] is False


@respx.mock
@pytest.mark.parametrize("name,type_,items", [
    ("", "PORTS", [1]), ("  ", "PORTS", [1]), (None, "PORTS", [1]),
    ("x", "BOGUS", [1]), ("x", "PORTS", []), ("x", "PORTS", [0]), ("x", "IPV4_ADDRESSES", ["bad"]),
])
async def test_create_validation(mock_client, name, type_, items):
    result = await tm.create_traffic_matching_list(mock_client, name, type_, items, confirm=True)
    assert result["category"] == "VALIDATION_ERROR" and len(respx.calls) == 0


# ---- update ----

@respx.mock
async def test_update_name_only_preserves_items(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_ports.json")))
    put = respx.put(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json={"id": P_ID}))
    result = await tm.update_traffic_matching_list(mock_client, P_ID, name="Renamed", confirm=True)
    assert result["executed"] is True
    sent = json.loads(put.calls[0].request.content)
    assert sent["name"] == "Renamed" and sent["type"] == "PORTS" and len(sent["items"]) == 3
    assert "id" not in sent


@respx.mock
async def test_update_items_only_and_preview(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_ports.json")))
    put = respx.put(f"{BASE}/{P_ID}")
    result = await tm.update_traffic_matching_list(mock_client, P_ID, items=[53])
    assert result["preview"] is True and not put.called
    assert result["list"] == {"type": "PORTS", "name": "Web ports", "items": [{"type": "PORT_NUMBER", "value": 53}]}
    assert result["current"]["name"] == "Web ports"
    assert await tm.update_traffic_matching_list(mock_client, P_ID, items=[53]) == result


@respx.mock
async def test_update_not_found_and_noop(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(404, json={}))
    assert (await tm.update_traffic_matching_list(mock_client, P_ID, name="x"))["category"] == "NOT_FOUND"
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_ports.json")))
    respx.put(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json={"data": []}))
    result = await tm.update_traffic_matching_list(mock_client, P_ID, name="x", confirm=True)
    assert result["executed"] is False


@respx.mock
async def test_update_validation(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_ports.json")))
    assert (await tm.update_traffic_matching_list(mock_client, P_ID))["category"] == "VALIDATION_ERROR"
    assert (await tm.update_traffic_matching_list(mock_client, P_ID, name=""))["category"] == "VALIDATION_ERROR"
    # items validated against the existing list type (PORTS), so an IP is rejected
    result = await tm.update_traffic_matching_list(mock_client, P_ID, items=["192.0.2.1"])
    assert result["category"] == "VALIDATION_ERROR"


# ---- delete ----

@respx.mock
async def test_delete_preview_warns(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200, json=load_fixture("traffic_matching_lists_ports.json")))
    delete = respx.delete(f"{BASE}/{P_ID}")
    result = await tm.delete_traffic_matching_list(mock_client, P_ID)
    assert result["preview"] is True and "firewall policies" in result["impact"].lower()
    assert result["list"]["id"] == P_ID and result["list"]["type"] == "PORTS"
    assert not delete.called


@respx.mock
async def test_delete_preview_not_found(mock_client):
    respx.get(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(404, json={}))
    result = await tm.delete_traffic_matching_list(mock_client, P_ID)
    assert result["category"] == "NOT_FOUND" and "preview" not in result


@respx.mock
async def test_delete_confirmed(mock_client):
    route = respx.delete(f"{BASE}/{P_ID}").mock(return_value=httpx.Response(200))
    result = await tm.delete_traffic_matching_list(mock_client, P_ID, confirm=True)
    assert result["executed"] is True and route.called
