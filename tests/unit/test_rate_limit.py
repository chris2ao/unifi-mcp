"""HTTP 429 handling: bounded retries that honor Retry-After, then RATE_LIMITED.

UniFi Protect's Integration API allows 10 requests per second and answers
bursts with 429 plus `Retry-After: 1` (verified on Protect 7.2.105).
"""
import httpx
import pytest
import respx

from unifi_mcp.auth import client as client_module
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.errors import ErrorCategory, UnifiError, status_to_category

BASE = "https://192.168.1.1"
INFO = "/proxy/protect/integration/v1/meta/info"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-api-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


@pytest.fixture
def sleeps(monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)
    return waits


def _limited(retry_after: str | None = "1") -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(429, headers=headers)


def test_429_maps_to_rate_limited():
    assert status_to_category(429) == ErrorCategory.RATE_LIMITED


@respx.mock
async def test_get_retries_after_429_then_succeeds(client, sleeps):
    route = respx.get(f"{BASE}{INFO}").mock(side_effect=[
        _limited("1"),
        httpx.Response(200, json={"applicationVersion": "7.2.105"}),
    ])
    result = await client.get(INFO)
    assert result == {"applicationVersion": "7.2.105"}
    assert route.call_count == 2
    assert sleeps == [1.0]


@respx.mock
async def test_get_raises_rate_limited_after_bounded_retries(client, sleeps):
    route = respx.get(f"{BASE}{INFO}").mock(return_value=_limited("1"))
    with pytest.raises(UnifiError) as exc:
        await client.get(INFO)
    assert exc.value.category == ErrorCategory.RATE_LIMITED
    assert "429" in exc.value.message
    assert route.call_count == client_module.RATE_LIMIT_RETRIES + 1
    assert len(sleeps) == client_module.RATE_LIMIT_RETRIES


@respx.mock
async def test_missing_retry_after_uses_backoff(client, sleeps):
    respx.get(f"{BASE}{INFO}").mock(side_effect=[
        _limited(None),
        _limited(None),
        httpx.Response(200, json={}),
    ])
    await client.get(INFO)
    assert sleeps == [1.0, 2.0]


@respx.mock
async def test_retry_after_is_capped(client, sleeps):
    respx.get(f"{BASE}{INFO}").mock(side_effect=[
        _limited("120"),
        httpx.Response(200, json={}),
    ])
    await client.get(INFO)
    assert sleeps == [client_module.RATE_LIMIT_MAX_WAIT_SECONDS]


@respx.mock
async def test_unparseable_retry_after_falls_back_to_backoff(client, sleeps):
    respx.get(f"{BASE}{INFO}").mock(side_effect=[
        _limited("Wed, 21 Oct 2026 07:28:00 GMT"),
        httpx.Response(200, json={}),
    ])
    await client.get(INFO)
    assert sleeps == [1.0]


@respx.mock
async def test_post_also_retries(client, sleeps):
    path = "/proxy/network/v2/api/site/default/system-log/all"
    route = respx.post(f"{BASE}{path}").mock(side_effect=[
        _limited("1"),
        httpx.Response(200, json={"data": []}),
    ])
    assert await client.post(path, json={}) == {"data": []}
    assert route.call_count == 2


@respx.mock
async def test_get_binary_retries_after_429(client, sleeps):
    path = "/proxy/protect/integration/v1/cameras/cam1/snapshot"
    respx.get(f"{BASE}{path}").mock(side_effect=[
        _limited("1"),
        httpx.Response(200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"}),
    ])
    body, content_type = await client.get_binary(path)
    assert body == b"\xff\xd8jpeg"
    assert content_type == "image/jpeg"


@respx.mock
async def test_get_binary_raises_rate_limited(client, sleeps):
    path = "/proxy/protect/integration/v1/cameras/cam1/snapshot"
    respx.get(f"{BASE}{path}").mock(return_value=_limited("1"))
    with pytest.raises(UnifiError) as exc:
        await client.get_binary(path)
    assert exc.value.category == ErrorCategory.RATE_LIMITED


@respx.mock
async def test_each_attempt_is_logged_to_discovery(client, sleeps):
    respx.get(f"{BASE}{INFO}").mock(side_effect=[_limited("1"), httpx.Response(200, json={})])
    await client.get(INFO)
    statuses = [entry["status_code"] for entry in client.discovery.get_report()]
    assert statuses == [429, 200]


@pytest.mark.parametrize("status", [404, 500, 503])
@respx.mock
async def test_other_errors_are_not_retried(client, sleeps, status):
    route = respx.get(f"{BASE}{INFO}").mock(return_value=httpx.Response(status, json={}))
    with pytest.raises(UnifiError):
        await client.get(INFO)
    assert route.call_count == 1
    assert sleeps == []


@pytest.mark.parametrize("header", ["nan", "inf", "-3", "0", "-inf"])
@respx.mock
async def test_non_finite_or_non_positive_retry_after_uses_backoff(client, sleeps, header):
    respx.get(f"{BASE}{INFO}").mock(side_effect=[_limited(header), httpx.Response(200, json={})])
    await client.get(INFO)
    assert sleeps == [1.0]


async def test_probe_reraises_rate_limited(server, monkeypatch):
    async def limited_get(*args, **kwargs):
        raise UnifiError(ErrorCategory.RATE_LIMITED, "GET probe returned 429", endpoint=INFO)

    monkeypatch.setattr(server.client, "get", limited_get)
    with pytest.raises(UnifiError) as exc:
        await server._probe_product("protect")
    assert exc.value.category == ErrorCategory.RATE_LIMITED


async def test_probe_treats_other_errors_as_not_installed(server, monkeypatch):
    async def missing_get(*args, **kwargs):
        raise UnifiError(ErrorCategory.NOT_FOUND, "GET probe returned 404", endpoint=INFO)

    monkeypatch.setattr(server.client, "get", missing_get)
    assert await server._probe_product("protect") is False


async def test_loader_reports_rate_limit_instead_of_not_installed(server, monkeypatch):
    async def limited_get(*args, **kwargs):
        raise UnifiError(ErrorCategory.RATE_LIMITED, "GET probe returned 429", endpoint=INFO)

    monkeypatch.setattr(server.client, "get", limited_get)
    monkeypatch.setattr(server.registry, "is_loaded", lambda product: False)
    message = await server._register_groups("protect", None, None)
    assert "rate limited" in message.lower()
    assert INFO in message
    assert "not installed" not in message
