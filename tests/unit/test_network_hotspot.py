"""Tests for the official-API hotspot voucher tools (get, list v1, delete)."""

import json
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig

FIXTURES = Path(__file__).parent.parent / "fixtures"
SITE_UUID = "00000000-0000-0000-0000-000000000001"
URL = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/hotspot/vouchers"
V1_ID = "00000000-0000-0000-0000-0000000000c1"
V2_ID = "00000000-0000-0000-0000-0000000000c2"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    client = UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_hotspot_declarations():
    from unifi_mcp.tools.network import hotspot

    assert hotspot.TIER2_TOOLS == {"delete_voucher": "hotspot", "delete_vouchers": "hotspot"}
    names = {t.__name__ for t in hotspot.TOOLS}
    assert {"get_voucher", "delete_voucher", "delete_vouchers", "list_vouchers_v1"} <= names


@respx.mock
@pytest.mark.asyncio
async def test_list_vouchers_v1(mock_client):
    from unifi_mcp.tools.network.hotspot import list_vouchers_v1

    respx.get(URL).mock(return_value=httpx.Response(200, json=load_fixture("hotspot_vouchers.json")))
    result = await list_vouchers_v1(mock_client)
    assert [v["id"] for v in result] == [V1_ID, V2_ID]
    assert result[1]["guest_count"] == 1
    assert result[1]["expires_at"] == "2026-01-03T00:00:00Z"
    assert result[0]["time_limit_minutes"] == 1440


@respx.mock
@pytest.mark.asyncio
async def test_list_vouchers_v1_passes_filter_and_paginates(mock_client):
    from unifi_mcp.tools.network.hotspot import list_vouchers_v1

    fixture = load_fixture("hotspot_vouchers.json")
    first = {**fixture, "limit": 200, "totalCount": 201, "data": fixture["data"] * 100 + fixture["data"][:1]}
    first_page = {**first, "data": first["data"][:200]}
    second_page = {**first, "offset": 200, "data": first["data"][200:]}
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(200, json=first_page), httpx.Response(200, json=second_page)]
    )
    result = await list_vouchers_v1(mock_client, filter="expired.eq(false)")
    assert len(result) == 201
    assert route.calls[0].request.url.params["filter"] == "expired.eq(false)"
    assert route.calls[1].request.url.params["offset"] == "200"


@respx.mock
@pytest.mark.asyncio
async def test_list_vouchers_v1_empty(mock_client):
    from unifi_mcp.tools.network.hotspot import list_vouchers_v1

    respx.get(URL).mock(return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    assert await list_vouchers_v1(mock_client) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "   ", 5, "x" * 1001])
async def test_list_vouchers_v1_rejects_bad_filter(mock_client, bad):
    from unifi_mcp.tools.network.hotspot import list_vouchers_v1

    assert (await list_vouchers_v1(mock_client, filter=bad))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_get_voucher(mock_client):
    from unifi_mcp.tools.network.hotspot import get_voucher

    respx.get(f"{URL}/{V1_ID}").mock(
        return_value=httpx.Response(200, json=load_fixture("hotspot_voucher_detail.json"))
    )
    result = await get_voucher(mock_client, V1_ID)
    assert result["id"] == V1_ID
    assert result["guest_limit"] == 1
    assert result["expired"] is False


@respx.mock
@pytest.mark.asyncio
async def test_get_voucher_wrapped_and_not_found(mock_client):
    from unifi_mcp.tools.network.hotspot import get_voucher

    detail = load_fixture("hotspot_voucher_detail.json")
    respx.get(f"{URL}/{V1_ID}").mock(return_value=httpx.Response(200, json={"data": [detail]}))
    assert (await get_voucher(mock_client, V1_ID))["name"] == "hotel-guest"
    respx.get(f"{URL}/{V2_ID}").mock(return_value=httpx.Response(404, json={}))
    assert (await get_voucher(mock_client, V2_ID))["category"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a?b", "a#b", "a b", None])
async def test_voucher_id_validation(mock_client, bad):
    from unifi_mcp.tools.network.hotspot import delete_voucher, get_voucher

    assert (await get_voucher(mock_client, bad))["category"] == "VALIDATION_ERROR"
    assert (await delete_voucher(mock_client, bad, confirm=True))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_delete_voucher_preview_unused(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_voucher

    respx.get(f"{URL}/{V1_ID}").mock(
        return_value=httpx.Response(200, json=load_fixture("hotspot_voucher_detail.json"))
    )
    delete = respx.delete(f"{URL}/{V1_ID}").mock(return_value=httpx.Response(200, json={}))
    result = await delete_voucher(mock_client, V1_ID)
    assert result["preview"] is True
    assert result["action"] == "delete_voucher"
    assert result["voucher"]["id"] == V1_ID
    assert "no guest is affected" in result["impact"]
    assert delete.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_delete_voucher_preview_active_warns(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_voucher

    active = load_fixture("hotspot_vouchers.json")["data"][1]
    respx.get(f"{URL}/{V2_ID}").mock(return_value=httpx.Response(200, json=active))
    result = await delete_voucher(mock_client, V2_ID)
    assert "unauthorized" in result["impact"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_voucher_preview_not_found(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_voucher

    respx.get(f"{URL}/{V1_ID}").mock(return_value=httpx.Response(404, json={}))
    assert (await delete_voucher(mock_client, V1_ID))["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_delete_voucher_confirm(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_voucher

    mock_client.cache.set("hotspot:stale", {"x": 1}, 60.0)
    route = respx.delete(f"{URL}/{V1_ID}").mock(
        return_value=httpx.Response(200, json={"vouchersDeleted": 1})
    )
    result = await delete_voucher(mock_client, V1_ID, confirm=True)
    assert result["executed"] is True
    assert result["vouchers_deleted"] == 1
    assert route.call_count == 1
    assert mock_client.cache.get("hotspot:stale") is None


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"vouchersDeleted": 0}])
async def test_delete_voucher_silent_noop(mock_client, body):
    from unifi_mcp.tools.network.hotspot import delete_voucher

    respx.delete(f"{URL}/{V1_ID}").mock(return_value=httpx.Response(200, json=body))
    result = await delete_voucher(mock_client, V1_ID, confirm=True)
    assert result["executed"] is False
    assert "no vouchers deleted" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_preview_lists_matches(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    flt = "name.like('hotel*')"
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=load_fixture("hotspot_vouchers.json")))
    delete = respx.delete(url__startswith=URL).mock(return_value=httpx.Response(200, json={}))
    result = await delete_vouchers(mock_client, flt)
    assert result["preview"] is True
    assert result["match_count"] == 2
    assert len(result["matches"]) == 2
    assert result["matches_truncated"] is False
    assert "1 matching voucher(s) are active" in result["impact"]
    assert route.calls.last.request.url.params["filter"] == flt
    assert delete.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_preview_truncates_sample(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    rows = [{**load_fixture("hotspot_voucher_detail.json"), "id": f"id{i}"} for i in range(25)]
    respx.get(URL).mock(
        return_value=httpx.Response(200, json={"data": rows, "totalCount": 25, "limit": 200})
    )
    result = await delete_vouchers(mock_client, "expired.eq(false)")
    assert result["match_count"] == 25
    assert len(result["matches"]) == 20
    assert result["matches_truncated"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_preview_zero_matches(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    respx.get(URL).mock(return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    result = await delete_vouchers(mock_client, "expired.eq(true)")
    assert result["matched"] == 0 and result["executed"] is False
    assert "preview" not in result


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_preview_bad_filter_surfaces_error(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    respx.get(URL).mock(return_value=httpx.Response(400, json={}))
    result = await delete_vouchers(mock_client, "bogus(")
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_confirm_sends_encoded_filter(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    flt = "and(expired.eq(true), name.like('a b*'))"
    route = respx.delete(url__startswith=URL).mock(
        return_value=httpx.Response(200, json=load_fixture("hotspot_delete_result.json"))
    )
    result = await delete_vouchers(mock_client, flt, confirm=True)
    assert result["executed"] is True
    assert result["vouchers_deleted"] == 2
    sent = route.calls.last.request
    assert sent.url.params["filter"] == flt
    assert quote(flt, safe="") in str(sent.url)


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_confirm_zero_deleted(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    respx.delete(url__startswith=URL).mock(
        return_value=httpx.Response(200, json={"vouchersDeleted": 0})
    )
    result = await delete_vouchers(mock_client, "expired.eq(true)", confirm=True)
    assert result["executed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "  ", None, 3, "x" * 1001])
async def test_delete_vouchers_requires_filter(mock_client, bad):
    from unifi_mcp.tools.network.hotspot import delete_vouchers

    for confirm in (False, True):
        result = await delete_vouchers(mock_client, bad, confirm=confirm)
        assert result["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_delete_vouchers_preview_flags_capped_count(mock_client, monkeypatch):
    from unifi_mcp.tools.network import hotspot

    monkeypatch.setattr(hotspot, "_PREVIEW_MAX_ITEMS", 3)
    rows = [{**load_fixture("hotspot_voucher_detail.json"), "id": f"id{i}"} for i in range(5)]
    respx.get(URL).mock(return_value=httpx.Response(200, json={"data": rows, "totalCount": 5}))
    result = await hotspot.delete_vouchers(mock_client, "expired.eq(false)")
    assert result["count_capped"] is True
    assert "at least 3" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_voucher_preview_bypasses_cache(mock_client):
    from unifi_mcp.tools.network.hotspot import delete_voucher, get_voucher

    route = respx.get(f"{URL}/{V1_ID}").mock(
        return_value=httpx.Response(200, json=load_fixture("hotspot_voucher_detail.json"))
    )
    await get_voucher(mock_client, V1_ID)
    await delete_voucher(mock_client, V1_ID)
    assert route.call_count == 2
