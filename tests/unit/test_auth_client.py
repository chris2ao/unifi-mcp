import pytest
import httpx
import respx
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.errors import UnifiError, ErrorCategory


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-api-key")
    monkeypatch.setenv("UNIFI_SITE", "default")
    return UnifiConfig()


@pytest.fixture
def client(config):
    cache = TTLCache()
    discovery = DiscoveryRegistry()
    return UnifiClient(config, cache, discovery)


@respx.mock
@pytest.mark.asyncio
async def test_get_sends_api_key_header(client):
    route = respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sysinfo").mock(
        return_value=httpx.Response(200, json={"data": [{"version": "8.6.9"}]})
    )
    result = await client.get("/proxy/network/api/s/{site}/stat/sysinfo")
    assert route.called
    request = route.calls[0].request
    assert request.headers["X-API-Key"] == "test-api-key"
    assert result == {"data": [{"version": "8.6.9"}]}


@respx.mock
@pytest.mark.asyncio
async def test_get_replaces_site_placeholder(client):
    route = respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await client.get("/proxy/network/api/s/{site}/stat/device")
    assert route.called


@respx.mock
@pytest.mark.asyncio
async def test_get_uses_cache(client):
    route = respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(200, json={"data": [{"name": "AP-1"}]})
    )
    result1 = await client.get(
        "/proxy/network/api/s/{site}/stat/device",
        cache_category="devices", cache_ttl=30.0
    )
    result2 = await client.get(
        "/proxy/network/api/s/{site}/stat/device",
        cache_category="devices", cache_ttl=30.0
    )
    assert route.call_count == 1
    assert result1 == result2


@respx.mock
@pytest.mark.asyncio
async def test_get_auth_error_raises(client):
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(401, json={"meta": {"msg": "api.err.LoginRequired"}})
    )
    with pytest.raises(UnifiError) as exc_info:
        await client.get("/proxy/network/api/s/{site}/stat/device")
    assert exc_info.value.category == ErrorCategory.AUTH_ERROR


@respx.mock
@pytest.mark.asyncio
async def test_get_not_found_raises(client):
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device/badmac").mock(
        return_value=httpx.Response(404, json={})
    )
    with pytest.raises(UnifiError) as exc_info:
        await client.get("/proxy/network/api/s/{site}/stat/device/badmac")
    assert exc_info.value.category == ErrorCategory.NOT_FOUND


@respx.mock
@pytest.mark.asyncio
async def test_connection_error_raises(client):
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sysinfo").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    with pytest.raises(UnifiError) as exc_info:
        await client.get("/proxy/network/api/s/{site}/stat/sysinfo")
    assert exc_info.value.category == ErrorCategory.CONNECTION_ERROR


@respx.mock
@pytest.mark.asyncio
async def test_post_sends_json_body(client):
    route = respx.post("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json={"data": [{"_id": "abc"}]})
    )
    result = await client.post(
        "/proxy/network/api/s/{site}/rest/networkconf",
        json={"name": "IoT", "vlan": 100}
    )
    assert route.called
    assert result == {"data": [{"_id": "abc"}]}


@respx.mock
@pytest.mark.asyncio
async def test_site_id_resolver_fetches_and_caches_uuid(client):
    sites_route = respx.get("https://192.168.1.1/proxy/network/integration/v1/sites").mock(
        return_value=httpx.Response(200, json={
            "data": [
                {"id": "uuid-default", "internalReference": "default", "name": "Default"},
                {"id": "uuid-other", "internalReference": "other", "name": "Other"},
            ]
        })
    )
    zones_route = respx.get("https://192.168.1.1/proxy/network/integration/v1/sites/uuid-default/firewall/zones").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    await client.get("/proxy/network/integration/v1/sites/{site_id}/firewall/zones")
    await client.get("/proxy/network/integration/v1/sites/{site_id}/firewall/zones")

    assert sites_route.call_count == 1
    assert zones_route.call_count == 2
    assert client._site_id == "uuid-default"


@respx.mock
@pytest.mark.asyncio
async def test_site_id_resolver_raises_when_site_not_found(client):
    respx.get("https://192.168.1.1/proxy/network/integration/v1/sites").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "uuid-other", "internalReference": "other", "name": "Other"},
        ]})
    )
    with pytest.raises(UnifiError) as exc_info:
        await client.get("/proxy/network/integration/v1/sites/{site_id}/firewall/zones")
    assert exc_info.value.category == ErrorCategory.NOT_FOUND


@respx.mock
@pytest.mark.asyncio
async def test_non_json_response_raises_unexpected_response(client):
    respx.get("https://192.168.1.1/proxy/access/api/v2/bootstrap").mock(
        return_value=httpx.Response(
            200, text="<html>UniFi OS landing page</html>",
            headers={"content-type": "text/html"},
        )
    )
    with pytest.raises(UnifiError) as exc_info:
        await client.get("/proxy/access/api/v2/bootstrap")
    assert exc_info.value.category == ErrorCategory.UNEXPECTED_RESPONSE


@respx.mock
@pytest.mark.asyncio
async def test_patch_sends_json_body(client):
    route = respx.patch(
        "https://192.168.1.1/proxy/protect/integration/v1/cameras/abc123"
    ).mock(return_value=httpx.Response(200, json={"id": "abc123", "name": "Front Porch"}))
    result = await client.patch(
        "/proxy/protect/integration/v1/cameras/abc123",
        json={"name": "Front Porch"},
    )
    assert route.called
    assert route.calls.last.request.content == b'{"name":"Front Porch"}'
    assert result == {"id": "abc123", "name": "Front Porch"}


@respx.mock
@pytest.mark.asyncio
async def test_discovery_logs_requests(client):
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sysinfo").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await client.get("/proxy/network/api/s/{site}/stat/sysinfo")
    report = client.discovery.get_report()
    assert len(report) == 1
    assert report[0]["endpoint"] == "/proxy/network/api/s/default/stat/sysinfo"
    assert report[0]["method"] == "GET"
    assert report[0]["status_code"] == 200


# --- Query parameters and Integration API pagination (v0.5.1) ---

INTEG = "https://192.168.1.1/proxy/network/integration/v1/sites/uuid-1/clients"


@pytest.fixture
def site_client(client):
    client._site_id = "uuid-1"
    return client


@respx.mock
@pytest.mark.asyncio
async def test_get_encodes_query_params(client):
    route = respx.get("https://192.168.1.1/proxy/network/integration/v1/sites").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await client.get(
        "/proxy/network/integration/v1/sites",
        params={"filter": "name.eq('Office AP')", "limit": 5, "skip": None},
    )
    request = route.calls.last.request
    assert request.url.params["filter"] == "name.eq('Office AP')"
    assert request.url.params["limit"] == "5"
    assert "skip" not in request.url.params
    # Spaces and quotes must be percent-encoded on the wire.
    assert b" " not in request.url.raw_path


@respx.mock
@pytest.mark.asyncio
async def test_get_without_params_sends_no_query(client):
    route = respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/device").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await client.get("/proxy/network/api/s/{site}/stat/device")
    assert route.calls.last.request.url.query == b""


@respx.mock
@pytest.mark.asyncio
async def test_get_bool_params_are_lowercase(client):
    route = respx.get("https://192.168.1.1/x").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.get("/x", params={"flag": True, "other": False})
    assert route.calls.last.request.url.params["flag"] == "true"
    assert route.calls.last.request.url.params["other"] == "false"


@respx.mock
@pytest.mark.asyncio
async def test_get_cache_key_includes_params(client):
    route = respx.get("https://192.168.1.1/x").mock(
        side_effect=[
            httpx.Response(200, json={"n": 1}),
            httpx.Response(200, json={"n": 2}),
        ]
    )
    a = await client.get("/x", cache_category="c", cache_ttl=30.0, params={"offset": 0})
    b = await client.get("/x", cache_category="c", cache_ttl=30.0, params={"offset": 25})
    a2 = await client.get("/x", cache_category="c", cache_ttl=30.0, params={"offset": 0})
    assert a == {"n": 1}
    assert b == {"n": 2}
    assert a2 == {"n": 1}
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_params_cache_invalidated_by_category(client):
    route = respx.get("https://192.168.1.1/x").mock(
        return_value=httpx.Response(200, json={"n": 1})
    )
    await client.get("/x", cache_category="c", cache_ttl=30.0, params={"offset": 0})
    client.invalidate_cache("c")
    await client.get("/x", cache_category="c", cache_ttl=30.0, params={"offset": 0})
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_does_not_mutate_params(client):
    respx.get("https://192.168.1.1/x").mock(return_value=httpx.Response(200, json={}))
    params = {"a": 1, "b": None}
    await client.get("/x", params=params)
    assert params == {"a": 1, "b": None}


def _page(items, offset, total):
    return {"offset": offset, "limit": len(items), "count": len(items),
            "totalCount": total, "data": items}


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_follows_offsets_until_total(site_client):
    route = respx.get(INTEG).mock(side_effect=[
        httpx.Response(200, json=_page([{"id": 1}, {"id": 2}], 0, 5)),
        httpx.Response(200, json=_page([{"id": 3}, {"id": 4}], 2, 5)),
        httpx.Response(200, json=_page([{"id": 5}], 4, 5)),
    ])
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients", page_size=2,
    )
    assert [i["id"] for i in items] == [1, 2, 3, 4, 5]
    offsets = [c.request.url.params["offset"] for c in route.calls]
    limits = [c.request.url.params["limit"] for c in route.calls]
    assert offsets == ["0", "2", "4"]
    assert limits == ["2", "2", "2"]


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_stops_when_total_reached_exactly(site_client):
    route = respx.get(INTEG).mock(side_effect=[
        httpx.Response(200, json=_page([{"id": 1}, {"id": 2}], 0, 4)),
        httpx.Response(200, json=_page([{"id": 3}, {"id": 4}], 2, 4)),
    ])
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients", page_size=2,
    )
    assert len(items) == 4
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_stops_on_short_page_without_total(site_client):
    route = respx.get(INTEG).mock(side_effect=[
        httpx.Response(200, json={"data": [{"id": 1}, {"id": 2}]}),
        httpx.Response(200, json={"data": [{"id": 3}]}),
    ])
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients", page_size=2,
    )
    assert len(items) == 3
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_stops_on_empty_page(site_client):
    route = respx.get(INTEG).mock(side_effect=[
        httpx.Response(200, json={"data": [{"id": 1}, {"id": 2}]}),
        httpx.Response(200, json={"data": []}),
    ])
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients", page_size=2,
    )
    assert len(items) == 2
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_respects_max_items(site_client):
    route = respx.get(INTEG).mock(side_effect=[
        httpx.Response(200, json=_page([{"id": i} for i in range(3)], 0, 100)),
        httpx.Response(200, json=_page([{"id": i} for i in range(3, 5)], 3, 100)),
    ])
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients",
        page_size=3, max_items=5,
    )
    assert len(items) == 5
    assert route.call_count == 2
    # The last request only asks for what is still needed.
    assert route.calls.last.request.url.params["limit"] == "2"


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_passes_filter_and_defaults(site_client):
    route = respx.get(INTEG).mock(
        return_value=httpx.Response(200, json=_page([{"id": 1}], 0, 1))
    )
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients",
        filter="type.eq('WIRED')",
    )
    assert items == [{"id": 1}]
    params = route.calls.last.request.url.params
    assert params["filter"] == "type.eq('WIRED')"
    assert params["limit"] == "200"
    assert params["offset"] == "0"


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_bare_list_response(site_client):
    route = respx.get(INTEG).mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    )
    items = await site_client.get_all_pages(
        "/proxy/network/integration/v1/sites/{site_id}/clients", max_items=1,
    )
    assert items == [{"id": 1}]
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_get_all_pages_uses_cache(site_client):
    route = respx.get(INTEG).mock(
        return_value=httpx.Response(200, json=_page([{"id": 1}], 0, 1))
    )
    for _ in range(2):
        await site_client.get_all_pages(
            "/proxy/network/integration/v1/sites/{site_id}/clients",
            cache_category="clients", cache_ttl=30.0,
        )
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_get_all_pages_zero_max_items_makes_no_call(site_client):
    assert await site_client.get_all_pages("/x", max_items=0) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, -1, 1001])
async def test_get_all_pages_rejects_bad_page_size(site_client, size):
    with pytest.raises(ValueError):
        await site_client.get_all_pages("/x", page_size=size)


def test_page_items_handles_unexpected_shapes():
    from unifi_mcp.auth.client import _page_items

    assert _page_items(None) == ([], None)
    assert _page_items({"data": "x", "totalCount": "5"}) == ([], None)
    assert _page_items({"data": [1], "totalCount": 1}) == ([1], 1)
