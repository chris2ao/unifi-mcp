"""Tests for the Tier 1 lookup tools (WANs, VPN, tags, DPI, countries, switching, RADIUS)."""

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
BASE = "https://192.168.1.1/proxy/network/integration/v1"
SITE = f"{BASE}/sites/{SITE_UUID}"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    client = UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def fx(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_module_declarations():
    from unifi_mcp.tools.network import lookups

    assert lookups.GROUP == "core"
    assert lookups.TIER2_TOOLS == {}
    assert len(lookups.TOOLS) == 14
    import inspect
    for tool in lookups.TOOLS:
        assert "confirm" not in inspect.signature(tool).parameters
        assert tool.__doc__


@respx.mock
@pytest.mark.asyncio
async def test_list_wans(mock_client):
    from unifi_mcp.tools.network.lookups import list_wans

    respx.get(f"{SITE}/wans").mock(return_value=httpx.Response(200, json=fx("lookups_wans.json")))
    assert await list_wans(mock_client) == [
        {"id": "00000000-0000-0000-0000-000000000011", "name": "Internet 1"},
        {"id": "00000000-0000-0000-0000-000000000012", "name": "Internet 2"},
    ]


@respx.mock
@pytest.mark.asyncio
async def test_lists_paginate_beyond_first_page(mock_client):
    from unifi_mcp.tools.network.lookups import list_wans

    rows = [{"id": f"id{i}", "name": f"WAN {i}"} for i in range(250)]
    route = respx.get(f"{SITE}/wans").mock(
        side_effect=[
            httpx.Response(200, json={"data": rows[:200], "totalCount": 250}),
            httpx.Response(200, json={"data": rows[200:], "totalCount": 250}),
        ]
    )
    assert len(await list_wans(mock_client)) == 250
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_empty_and_bare_list_shapes(mock_client):
    from unifi_mcp.tools.network.lookups import list_device_tags, list_wans

    respx.get(f"{SITE}/device-tags").mock(return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    assert await list_device_tags(mock_client) == []
    respx.get(f"{SITE}/wans").mock(return_value=httpx.Response(200, json=[{"id": "w1", "name": "WAN"}]))
    assert await list_wans(mock_client) == [{"id": "w1", "name": "WAN"}]


@respx.mock
@pytest.mark.asyncio
async def test_list_site_to_site_tunnels(mock_client):
    from unifi_mcp.tools.network.lookups import list_site_to_site_tunnels

    respx.get(f"{SITE}/vpn/site-to-site-tunnels").mock(
        return_value=httpx.Response(200, json=fx("lookups_s2s_tunnels.json"))
    )
    result = await list_site_to_site_tunnels(mock_client)
    assert result[0]["name"] == "Branch Office"
    assert result[0]["type"] == "IPSEC"
    assert result[0]["origin"] == "USER_DEFINED"


@respx.mock
@pytest.mark.asyncio
async def test_list_device_tags(mock_client):
    from unifi_mcp.tools.network.lookups import list_device_tags

    respx.get(f"{SITE}/device-tags").mock(return_value=httpx.Response(200, json=fx("lookups_device_tags.json")))
    result = await list_device_tags(mock_client)
    assert result[0]["name"] == "Upstairs"
    assert result[0]["device_count"] == 2


@respx.mock
@pytest.mark.asyncio
async def test_search_dpi_applications_ranks_prefix_first(mock_client):
    from unifi_mcp.tools.network.lookups import search_dpi_applications

    respx.get(f"{BASE}/dpi/applications").mock(
        return_value=httpx.Response(200, json=fx("lookups_dpi_applications.json"))
    )
    result = await search_dpi_applications(mock_client, "ZOOM")
    assert [a["name"] for a in result] == ["Zoom", "ZoomSpider crawler"]
    assert result[0]["id"] == 1114174
    mid = await search_dpi_applications(mock_client, "press")
    assert [a["name"] for a in mid] == ["Adobe Express"]


@respx.mock
@pytest.mark.asyncio
async def test_search_dpi_applications_limit_and_no_match(mock_client):
    from unifi_mcp.tools.network.lookups import search_dpi_applications

    respx.get(f"{BASE}/dpi/applications").mock(
        return_value=httpx.Response(200, json=fx("lookups_dpi_applications.json"))
    )
    assert len(await search_dpi_applications(mock_client, "zoom", limit=1)) == 1
    assert await search_dpi_applications(mock_client, "nonexistent") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"query": ""}, {"query": "  "}, {"query": 5}, {"query": "a", "limit": 0}, {"query": "a", "limit": 201}])
async def test_search_dpi_applications_validation(mock_client, kwargs):
    from unifi_mcp.tools.network.lookups import search_dpi_applications

    assert (await search_dpi_applications(mock_client, **kwargs))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_list_dpi_categories(mock_client):
    from unifi_mcp.tools.network.lookups import list_dpi_categories

    respx.get(f"{BASE}/dpi/categories").mock(return_value=httpx.Response(200, json=fx("lookups_dpi_categories.json")))
    assert (await list_dpi_categories(mock_client))[1] == {"id": 5, "name": "Business tools"}


@respx.mock
@pytest.mark.asyncio
async def test_list_countries_all_and_query(mock_client):
    from unifi_mcp.tools.network.lookups import list_countries

    respx.get(f"{BASE}/countries").mock(return_value=httpx.Response(200, json=fx("lookups_countries.json")))
    assert len(await list_countries(mock_client)) == 3
    assert [c["code"] for c in await list_countries(mock_client, "ger")] == ["DE"]
    assert [c["name"] for c in await list_countries(mock_client, "ky")] == ["Cayman Islands"]
    assert await list_countries(mock_client, "zzz") == []
    assert len(await list_countries(mock_client, "  ")) == 3


@pytest.mark.asyncio
async def test_list_countries_validation(mock_client):
    from unifi_mcp.tools.network.lookups import list_countries

    assert (await list_countries(mock_client, 5))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_switch_stacks(mock_client):
    from unifi_mcp.tools.network.lookups import get_switch_stack, list_switch_stacks

    respx.get(f"{SITE}/switching/switch-stacks").mock(
        return_value=httpx.Response(200, json=fx("lookups_switch_stacks.json"))
    )
    stacks = await list_switch_stacks(mock_client)
    assert stacks[0]["name"] == "Rack Stack"
    assert stacks[0]["units"][0]["role"] == "ACTIVE_CONTROLLER"
    assert stacks[0]["lag_ids"] == ["00000000-0000-0000-0000-000000000051"]

    sid = "00000000-0000-0000-0000-000000000041"
    respx.get(f"{SITE}/switching/switch-stacks/{sid}").mock(
        return_value=httpx.Response(200, json=fx("lookups_switch_stack_detail.json"))
    )
    assert (await get_switch_stack(mock_client, sid))["units"][1]["mac"] == "aa:bb:cc:00:00:e2"


@respx.mock
@pytest.mark.asyncio
async def test_lags(mock_client):
    from unifi_mcp.tools.network.lookups import get_lag, list_lags

    respx.get(f"{SITE}/switching/lags").mock(return_value=httpx.Response(200, json=fx("lookups_lags.json")))
    lags = await list_lags(mock_client)
    assert [lag["type"] for lag in lags] == ["LOCAL", "SWITCH_STACK"]
    assert lags[1]["switch_stack_id"] == "00000000-0000-0000-0000-000000000041"
    assert lags[0]["switch_stack_id"] is None

    lid = "00000000-0000-0000-0000-000000000052"
    respx.get(f"{SITE}/switching/lags/{lid}").mock(return_value=httpx.Response(200, json=fx("lookups_lag_detail.json")))
    assert (await get_lag(mock_client, lid))["members"][0]["portIdxs"] == [3, 4]


@respx.mock
@pytest.mark.asyncio
async def test_mc_lag_domains(mock_client):
    from unifi_mcp.tools.network.lookups import get_mc_lag_domain, list_mc_lag_domains

    respx.get(f"{SITE}/switching/mc-lag-domains").mock(
        return_value=httpx.Response(200, json=fx("lookups_mc_lag_domains.json"))
    )
    domains = await list_mc_lag_domains(mock_client)
    assert domains[0]["peers"][0] == {
        "role": "TOP", "device_id": "00000000-0000-0000-0000-0000000000d1", "link_port_idxs": [25, 26],
    }
    assert domains[0]["lags"][0]["id"] == "00000000-0000-0000-0000-000000000062"

    did = "00000000-0000-0000-0000-000000000061"
    respx.get(f"{SITE}/switching/mc-lag-domains/{did}").mock(
        return_value=httpx.Response(200, json=fx("lookups_mc_lag_domain_detail.json"))
    )
    assert (await get_mc_lag_domain(mock_client, did))["name"] == "Core MC-LAG"


@respx.mock
@pytest.mark.asyncio
async def test_get_by_id_not_found_empty_and_wrapped(mock_client):
    from unifi_mcp.tools.network.lookups import get_lag

    respx.get(f"{SITE}/switching/lags/missing").mock(return_value=httpx.Response(404, json={}))
    assert (await get_lag(mock_client, "missing"))["category"] == "NOT_FOUND"
    respx.get(f"{SITE}/switching/lags/empty").mock(return_value=httpx.Response(200, json={}))
    assert (await get_lag(mock_client, "empty"))["category"] == "NOT_FOUND"
    respx.get(f"{SITE}/switching/lags/wrapped").mock(
        return_value=httpx.Response(200, json={"data": [fx("lookups_lag_detail.json")]})
    )
    assert (await get_lag(mock_client, "wrapped"))["type"] == "LOCAL"
    respx.get(f"{SITE}/switching/lags/nodata").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await get_lag(mock_client, "nodata"))["category"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a?b", "a#b", "a b", None])
async def test_get_tools_validate_ids(mock_client, bad):
    from unifi_mcp.tools.network.lookups import get_lag, get_mc_lag_domain, get_switch_stack

    for tool in (get_switch_stack, get_lag, get_mc_lag_domain):
        assert (await tool(mock_client, bad))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_list_radius_profiles_v1_has_no_secrets(mock_client):
    from unifi_mcp.tools.network.lookups import list_radius_profiles_v1

    data = fx("lookups_radius_profiles.json")
    data["data"][0]["sharedSecret"] = "hunter2"
    respx.get(f"{SITE}/radius/profiles").mock(return_value=httpx.Response(200, json=data))
    result = await list_radius_profiles_v1(mock_client)
    assert result == [{"id": "00000000-0000-0000-0000-000000000071", "name": "Default RADIUS", "origin": "SYSTEM_DEFINED"}]
    assert "hunter2" not in json.dumps(result)


@respx.mock
@pytest.mark.asyncio
async def test_list_vpn_servers_v1(mock_client):
    from unifi_mcp.tools.network.lookups import list_vpn_servers_v1

    respx.get(f"{SITE}/vpn/servers").mock(return_value=httpx.Response(200, json=fx("lookups_vpn_servers.json")))
    result = await list_vpn_servers_v1(mock_client)
    assert [s["type"] for s in result] == ["OPENVPN", "UID"]
    assert result[1]["enabled"] is False


@respx.mock
@pytest.mark.asyncio
async def test_lists_tolerate_odd_shapes(mock_client):
    from unifi_mcp.tools.network.lookups import list_lags, list_mc_lag_domains, list_switch_stacks

    respx.get(f"{SITE}/switching/switch-stacks").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "s1", "name": "S", "units": None, "lags": None}, "junk"]})
    )
    assert (await list_switch_stacks(mock_client))[0]["units"] == []
    respx.get(f"{SITE}/switching/lags").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "l1", "type": "LOCAL", "members": None}]})
    )
    assert (await list_lags(mock_client))[0]["members"] == []
    respx.get(f"{SITE}/switching/mc-lag-domains").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "d1", "name": "D", "peers": None, "lags": None}]})
    )
    assert (await list_mc_lag_domains(mock_client))[0]["peers"] == []


@respx.mock
@pytest.mark.asyncio
async def test_connection_error_propagates_as_unifi_error(mock_client):
    from unifi_mcp.errors import UnifiError
    from unifi_mcp.tools.network.lookups import list_wans

    respx.get(f"{SITE}/wans").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(UnifiError):
        await list_wans(mock_client)
