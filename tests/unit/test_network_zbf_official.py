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
from unifi_mcp.tools.network import zbf_official as zo
from unifi_mcp.tools.network import zbf_zones_official as zz

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


FW = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/firewall"
P1 = "00000000-0000-0000-0000-000000000101"
P2 = "00000000-0000-0000-0000-000000000102"
P3 = "00000000-0000-0000-0000-000000000103"
Z1 = "00000000-0000-0000-0000-0000000000a1"
Z2 = "00000000-0000-0000-0000-0000000000a2"
NET = "00000000-0000-0000-0000-0000000000b1"
V2_ID = "000000000000000000000001"


def test_module_declarations():
    assert zo.GROUP == "security"
    assert set(zo.TIER2_TOOLS) == {
        "toggle_zbf_policy", "set_zbf_policy_logging", "reorder_zbf_policies",
    }
    assert set(zz.TIER2_TOOLS) == {"create_zbf_zone", "update_zbf_zone", "delete_zbf_zone"}
    assert zz.GROUP == "security"
    for mod in (zo, zz):
        assert all(v == "zbf" for v in mod.TIER2_TOOLS.values())
        assert {f.__name__ for f in mod.TOOLS} >= set(mod.TIER2_TOOLS)


def test_legacy_module_declares_tier2():
    from unifi_mcp.tools.network import zbf
    assert set(zbf.TIER2_TOOLS) == {"create_zbf_policy", "update_zbf_policy", "delete_zbf_policy"}


@respx.mock
async def test_get_zbf_policy(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_policy_v1.json")))
    r = await zo.get_zbf_policy(mock_client, P1)
    assert r["id"] == P1 and r["name"] == "Allow Office to Servers"
    assert r["action"] == "ALLOW" and r["source_zone_id"] == Z1
    assert r["origin"] == "USER_DEFINED" and "source" in r


@respx.mock
async def test_get_zbf_policy_wrapped_shape(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json={"data": [load_fixture("zbf_policy_v1.json")]}))
    assert (await zo.get_zbf_policy(mock_client, P1))["id"] == P1


@respx.mock
async def test_get_zbf_policy_empty_is_not_found(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(200, json={"data": []}))
    r = await zo.get_zbf_policy(mock_client, P1)
    assert r["error"] and r["category"] == "NOT_FOUND"


@respx.mock
async def test_get_zbf_policy_http_404_raises(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(404, json={}))
    with pytest.raises(UnifiError):
        await zo.get_zbf_policy(mock_client, P1)


@pytest.mark.parametrize("bad", [V2_ID, "", "../x", "abc/def", None, 5])
async def test_get_zbf_policy_rejects_non_uuid(mock_client, bad):
    r = await zo.get_zbf_policy(mock_client, bad)
    assert r["error"] and r["category"] == "VALIDATION_ERROR"
    assert "list_zbf_policies_v1" in r["message"]


@respx.mock
async def test_list_v1_paginates_and_filters_zones(mock_client):
    fx = load_fixture("zbf_policies_v1.json")
    route = respx.get(f"{FW}/policies").mock(return_value=httpx.Response(200, json=fx))
    rows = await zo.list_zbf_policies_v1(mock_client)
    assert len(rows) == 5 and route.calls[0].request.url.params["offset"] == "0"
    rows = await zo.list_zbf_policies_v1(mock_client, source_zone_id=Z1, destination_zone_id=Z2)
    assert [r["id"] for r in rows] == [P1, P2, P3, "00000000-0000-0000-0000-000000000105"]
    rows = await zo.list_zbf_policies_v1(mock_client, source_zone_id=Z2)
    assert [r["name"] for r in rows] == ["Other Pair"]


@respx.mock
async def test_list_v1_multi_page(mock_client):
    items = load_fixture("zbf_policies_v1.json")["data"]
    calls = []

    def handler(request):
        calls.append(dict(request.url.params))
        off = int(request.url.params["offset"])
        return httpx.Response(200, json={"data": items[off:off + 2], "totalCount": 5})

    respx.get(f"{FW}/policies").mock(side_effect=handler)
    # page_size is the client default; emulate small pages via monkeypatched helper
    from unifi_mcp.auth import client as cmod
    orig = cmod.INTEGRATION_PAGE_SIZE
    rows = await mock_client.get_all_pages(f"{zo._BASE}/policies", page_size=2)
    assert len(rows) == 5 and len(calls) == 3 and orig == cmod.INTEGRATION_PAGE_SIZE


@respx.mock
async def test_list_v1_passes_filter(mock_client):
    route = respx.get(f"{FW}/policies").mock(
        return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    assert await zo.list_zbf_policies_v1(mock_client, filter="name.eq('x')") == []
    assert route.calls[0].request.url.params["filter"] == "name.eq('x')"


async def test_list_v1_validation(mock_client):
    assert (await zo.list_zbf_policies_v1(mock_client, source_zone_id="nope"))[0]["error"]
    assert (await zo.list_zbf_policies_v1(mock_client, destination_zone_id=V2_ID))[0]["error"]
    assert (await zo.list_zbf_policies_v1(mock_client, filter=5))[0]["error"]


@respx.mock
async def test_toggle_preview_reads_only(mock_client):
    get = respx.get(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_policy_v1.json")))
    put = respx.put(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(200, json={}))
    a = await zo.toggle_zbf_policy(mock_client, P1, False)
    b = await zo.toggle_zbf_policy(mock_client, P1, False)
    assert a == b and a["preview"] and a["current_enabled"] is True and a["enabled"] is False
    assert "impact" in a and get.called and not put.called


@respx.mock
async def test_toggle_confirm_puts_merged_body(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_policy_v1.json")))
    put = respx.put(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json={"id": P1, "enabled": False}))
    r = await zo.toggle_zbf_policy(mock_client, P1, False, confirm=True)
    assert r["executed"] is True and r["action"] == "toggle_zbf_policy"
    body = json.loads(put.calls[0].request.content)
    assert body["enabled"] is False and body["name"] == "Allow Office to Servers"
    assert "id" not in body and "metadata" not in body and "index" not in body


@respx.mock
async def test_toggle_empty_response_is_not_executed(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_policy_v1.json")))
    respx.put(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(200, json={}))
    r = await zo.toggle_zbf_policy(mock_client, P1, True, confirm=True)
    assert r["executed"] is False and "ignored" in r["message"]


@respx.mock
async def test_toggle_not_found_and_validation(mock_client):
    respx.get(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await zo.toggle_zbf_policy(mock_client, P1, True))["category"] == "NOT_FOUND"
    assert (await zo.toggle_zbf_policy(mock_client, V2_ID, True))["category"] == "VALIDATION_ERROR"
    assert (await zo.toggle_zbf_policy(mock_client, P1, "yes"))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_set_logging_preview_and_confirm(mock_client):
    patch = respx.patch(f"{FW}/policies/{P1}").mock(
        return_value=httpx.Response(200, json={"id": P1, "loggingEnabled": True}))
    pv = await zo.set_zbf_policy_logging(mock_client, P1, True)
    assert pv["preview"] and pv["logging_enabled"] is True and not patch.called
    r = await zo.set_zbf_policy_logging(mock_client, P1, True, confirm=True)
    assert r["executed"] and json.loads(patch.calls[0].request.content) == {"loggingEnabled": True}


@respx.mock
async def test_set_logging_empty_and_validation(mock_client):
    respx.patch(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(200, json={}))
    assert (await zo.set_zbf_policy_logging(mock_client, P1, True, confirm=True))["executed"] is False
    assert (await zo.set_zbf_policy_logging(mock_client, "x", True))["error"]
    assert (await zo.set_zbf_policy_logging(mock_client, P1, None))["error"]


@respx.mock
async def test_get_order_sends_required_query(mock_client):
    route = respx.get(f"{FW}/policies/ordering").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_ordering.json")))
    r = await zo.get_zbf_policy_order(mock_client, Z1, Z2)
    q = route.calls[0].request.url.params
    assert q["sourceFirewallZoneId"] == Z1 and q["destinationFirewallZoneId"] == Z2
    assert r["before_system_defined"] == [P1, P2] and r["after_system_defined"] == [P3]
    assert r["total"] == 3


async def test_get_order_validation(mock_client):
    assert (await zo.get_zbf_policy_order(mock_client, "bad", Z2))["error"]
    assert (await zo.get_zbf_policy_order(mock_client, Z1, "bad"))["error"]


def _mock_order(**kw):
    return respx.get(f"{FW}/policies/ordering").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_ordering.json")))


@respx.mock
async def test_reorder_preview_shows_before_after(mock_client):
    _mock_order()
    put = respx.put(f"{FW}/policies/ordering").mock(return_value=httpx.Response(200, json={}))
    r = await zo.reorder_zbf_policies(mock_client, Z1, Z2, [P3, P1, P2])
    assert r["preview"] and "impact" in r and r["changed"] is True
    assert r["order_before"]["before_system_defined"] == [P1, P2]
    assert r["order_after"]["before_system_defined"] == [P3, P1]
    assert r["order_after"]["after_system_defined"] == [P2]
    assert not put.called
    assert r == await zo.reorder_zbf_policies(mock_client, Z1, Z2, [P3, P1, P2])


@respx.mock
async def test_reorder_confirm_puts_ordering(mock_client):
    _mock_order()
    put = respx.put(url__regex=rf"{FW}/policies/ordering\?.*").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_ordering.json")))
    r = await zo.reorder_zbf_policies(mock_client, Z1, Z2, [P2, P1, P3], confirm=True)
    assert r["executed"]
    req = put.calls[0].request
    assert req.url.params["sourceFirewallZoneId"] == Z1
    assert json.loads(req.content) == {"orderedFirewallPolicyIds": {
        "beforeSystemDefined": [P2, P1], "afterSystemDefined": [P3]}}


@respx.mock
async def test_reorder_explicit_after_section(mock_client):
    _mock_order()
    r = await zo.reorder_zbf_policies(
        mock_client, Z1, Z2, [P1], after_system_defined_ids=[P2, P3])
    assert r["order_after"] == {"before_system_defined": [P1], "after_system_defined": [P2, P3]}


@respx.mock
@pytest.mark.parametrize("ids", [[P1, P2], [P1, P2, P3, "00000000-0000-0000-0000-000000000199"],
                                  [P1, P1, P2]])
async def test_reorder_rejects_set_mismatch(mock_client, ids):
    _mock_order()
    put = respx.put(url__regex=rf"{FW}/policies/ordering.*").mock(return_value=httpx.Response(200, json={}))
    r = await zo.reorder_zbf_policies(mock_client, Z1, Z2, ids, confirm=True)
    assert r["category"] == "VALIDATION_ERROR" and not put.called


async def test_reorder_input_validation(mock_client):
    assert (await zo.reorder_zbf_policies(mock_client, "x", Z2, [P1]))["error"]
    assert (await zo.reorder_zbf_policies(mock_client, Z1, Z2, "nope"))["error"]
    assert (await zo.reorder_zbf_policies(mock_client, Z1, Z2, [V2_ID]))["error"]
    assert (await zo.reorder_zbf_policies(mock_client, Z1, Z2, [P1], after_system_defined_ids=["z"]))["error"]


@respx.mock
async def test_reorder_empty_put_response(mock_client):
    _mock_order()
    respx.put(url__regex=rf"{FW}/policies/ordering.*").mock(return_value=httpx.Response(200, json={}))
    r = await zo.reorder_zbf_policies(mock_client, Z1, Z2, [P1, P2, P3], confirm=True)
    assert r["executed"] is False


@respx.mock
async def test_create_zone(mock_client):
    post = respx.post(f"{FW}/zones").mock(
        return_value=httpx.Response(201, json=load_fixture("zbf_zone_custom.json")))
    pv = await zz.create_zbf_zone(mock_client, "Office Zone", [NET])
    assert pv["preview"] and not post.called
    r = await zz.create_zbf_zone(mock_client, "Office Zone", [NET], confirm=True)
    assert r["executed"] and json.loads(post.calls[0].request.content) == {
        "name": "Office Zone", "networkIds": [NET]}


async def test_create_zone_validation(mock_client):
    assert (await zz.create_zbf_zone(mock_client, "", []))["error"]
    assert (await zz.create_zbf_zone(mock_client, "x" * 200, []))["error"]
    assert (await zz.create_zbf_zone(mock_client, "ok", "net"))["error"]
    assert (await zz.create_zbf_zone(mock_client, "ok", ["bad"]))["error"]


@respx.mock
async def test_create_zone_empty_networks_allowed(mock_client):
    pv = await zz.create_zbf_zone(mock_client, "Empty", [])
    assert pv["preview"] and pv["network_ids"] == []


@respx.mock
async def test_update_zone_get_merge_put(mock_client):
    respx.get(f"{FW}/zones/{Z1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_zone_custom.json")))
    put = respx.put(f"{FW}/zones/{Z1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_zone_custom.json")))
    pv = await zz.update_zbf_zone(mock_client, Z1, name="Renamed")
    assert pv["preview"] and pv["updated"] == {"name": "Renamed", "network_ids": [NET]}
    assert pv["current"]["name"] == "Office Zone" and not put.called
    r = await zz.update_zbf_zone(mock_client, Z1, network_ids=[], confirm=True)
    assert r["executed"]
    assert json.loads(put.calls[0].request.content) == {"name": "Office Zone", "networkIds": []}


@respx.mock
async def test_update_zone_errors(mock_client):
    respx.get(f"{FW}/zones/{Z2}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_zone_system.json")))
    respx.get(f"{FW}/zones/{Z1}").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await zz.update_zbf_zone(mock_client, Z1, name="x"))["category"] == "NOT_FOUND"
    assert (await zz.update_zbf_zone(mock_client, Z2, name="Other"))["category"] == "VALIDATION_ERROR"
    assert (await zz.update_zbf_zone(mock_client, Z1))["category"] == "VALIDATION_ERROR"
    assert (await zz.update_zbf_zone(mock_client, "bad", name="x"))["error"]
    assert (await zz.update_zbf_zone(mock_client, Z1, name=""))["error"]
    assert (await zz.update_zbf_zone(mock_client, Z1, network_ids=["bad"]))["error"]
    ok = await zz.update_zbf_zone(mock_client, Z2, name="Internal", network_ids=[NET])
    assert ok["preview"]


@respx.mock
async def test_delete_zone_custom(mock_client):
    respx.get(f"{FW}/zones/{Z1}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_zone_custom.json")))
    delete = respx.delete(f"{FW}/zones/{Z1}").mock(return_value=httpx.Response(200, json={}))
    pv = await zz.delete_zbf_zone(mock_client, Z1)
    assert pv["preview"] and "impact" in pv and not delete.called
    r = await zz.delete_zbf_zone(mock_client, Z1, confirm=True)
    assert r["executed"] is True and delete.called


@respx.mock
async def test_delete_zone_system_refused_and_missing(mock_client):
    respx.get(f"{FW}/zones/{Z2}").mock(
        return_value=httpx.Response(200, json=load_fixture("zbf_zone_system.json")))
    respx.get(f"{FW}/zones/{Z1}").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await zz.delete_zbf_zone(mock_client, Z2, confirm=True))["category"] == "VALIDATION_ERROR"
    assert (await zz.delete_zbf_zone(mock_client, Z1))["category"] == "NOT_FOUND"
    assert (await zz.delete_zbf_zone(mock_client, "bad"))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_writes_invalidate_zbf_cache(mock_client):
    mock_client.cache.set("zbf:marker", {"x": 1}, 60)
    respx.patch(f"{FW}/policies/{P1}").mock(return_value=httpx.Response(200, json={"id": P1}))
    await zo.set_zbf_policy_logging(mock_client, P1, True, confirm=True)
    assert mock_client.cache.get("zbf:marker") is None


@respx.mock
async def test_create_zone_maps_legacy_network_id(mock_client):
    legacy = "000000000000000000000abc"
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/" + legacy).mock(
        return_value=httpx.Response(200, json={"data": [{"_id": legacy, "name": "IoT"}]}))
    respx.get(
        f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/networks"
    ).mock(return_value=httpx.Response(200, json={
        "data": [{"id": NET, "name": "IoT"}], "count": 1, "offset": 0, "limit": 200, "totalCount": 1}))
    post = respx.post(f"{FW}/zones").mock(return_value=httpx.Response(201, json={"id": Z1}))
    pv = await zz.create_zbf_zone(mock_client, "IoT Zone", [legacy])
    assert pv["preview"] and pv["network_ids"] == [NET]
    r = await zz.create_zbf_zone(mock_client, "IoT Zone", [legacy], confirm=True)
    assert r["executed"]
    assert json.loads(post.calls[0].request.content)["networkIds"] == [NET]


async def test_create_zone_network_error_names_networks_not_policies(mock_client):
    r = await zz.create_zbf_zone(mock_client, "x", ["bad"])
    assert r["category"] == "VALIDATION_ERROR"
    assert "list_networks" in r["message"] and "list_zbf_policies_v1" not in r["message"]
