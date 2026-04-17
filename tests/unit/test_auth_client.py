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
