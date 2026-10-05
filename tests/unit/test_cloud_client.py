import httpx
import pytest
import respx
from pydantic import ValidationError

from unifi_mcp.cloud.client import CloudClient, CloudRateLimitError
from unifi_mcp.cloud.config import CloudConfig
from unifi_mcp.errors import ErrorCategory, UnifiError
import json
from pathlib import Path


def load_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent.parent / "fixtures" / name).read_text())

BASE = "https://api.ui.com"
KEY = "cloud-secret-key-123"


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", KEY)
    monkeypatch.delenv("UNIFI_CLOUD_BASE_URL", raising=False)
    return CloudConfig()


@pytest.fixture
async def client(cfg):
    c = CloudClient(cfg)
    yield c
    await c.close()


def test_config_defaults(cfg):
    assert cfg.unifi_cloud_base_url == BASE
    assert cfg.has_key
    assert KEY not in repr(cfg)


def test_config_no_key(monkeypatch):
    monkeypatch.delenv("UNIFI_CLOUD_API_KEY", raising=False)
    assert not CloudConfig().has_key
    with pytest.raises(ValueError):
        CloudClient(CloudConfig())


def test_config_blank_key(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "  ")
    assert not CloudConfig().has_key


@pytest.mark.parametrize("url", [
    "http://api.ui.com", "https://evil.example.com", "https://ui.com.evil.com",
    "https://user:pw@api.ui.com", "ftp://api.ui.com",
])
def test_config_rejects_bad_base_url(monkeypatch, url):
    monkeypatch.setenv("UNIFI_CLOUD_BASE_URL", url)
    with pytest.raises(ValidationError):
        CloudConfig()


def test_config_accepts_ui_com_override(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_BASE_URL", "https://staging.api.ui.com/")
    assert CloudConfig().unifi_cloud_base_url == "https://staging.api.ui.com"


def test_repr_hides_key(client):
    assert KEY not in repr(client)


@respx.mock
async def test_header_and_get(client):
    route = respx.get(f"{BASE}/v1/hosts/h1").mock(return_value=httpx.Response(200, json={"data": {"id": "h1"}}))
    assert (await client.get("/v1/hosts/h1"))["data"]["id"] == "h1"
    assert route.calls[0].request.headers["x-api-key"] == KEY


@respx.mock
async def test_post(client):
    route = respx.post(f"{BASE}/v1/x").mock(return_value=httpx.Response(200, json={"ok": 1}))
    assert await client.post("/v1/x", json={"a": 1}) == {"ok": 1}
    assert route.calls[0].request.content == b'{"a":1}'


@respx.mock
async def test_pagination_follows_next_token(client):
    route = respx.get(f"{BASE}/v1/hosts").mock(side_effect=[
        httpx.Response(200, json=load_fixture("cloud/hosts.json")),
        httpx.Response(200, json=load_fixture("cloud/hosts_page2.json")),
    ])
    items = await client.get_paginated("/v1/hosts", page_size=1)
    assert len(items) == 2
    assert "nextToken=tok2" in str(route.calls[1].request.url)
    assert "pageSize=1" in str(route.calls[0].request.url)


@respx.mock
async def test_pagination_max_pages_and_shapes(client):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(200, json={"data": {"id": "x"}, "nextToken": "t"}))
    items = await client.get_paginated("/v1/hosts", params={"a": "1", "b": None}, max_pages=2)
    assert items == [{"id": "x"}, {"id": "x"}]


@respx.mock
async def test_pagination_bare_list(client):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(200, json=[]))
    assert await client.get_paginated("/v1/hosts") == []


@respx.mock
@pytest.mark.parametrize("status,category", [
    (400, ErrorCategory.VALIDATION_ERROR), (401, ErrorCategory.AUTH_ERROR),
    (403, ErrorCategory.AUTH_ERROR), (404, ErrorCategory.NOT_FOUND),
    (500, ErrorCategory.UNEXPECTED_RESPONSE), (502, ErrorCategory.PRODUCT_UNAVAILABLE),
])
async def test_error_mapping(client, status, category):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(status, json={"message": "nope", "httpStatusCode": status}))
    with pytest.raises(UnifiError) as exc:
        await client.get("/v1/hosts")
    assert exc.value.category == category
    assert KEY not in str(exc.value)


@respx.mock
async def test_rate_limit_retry_after(client):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(429, headers={"Retry-After": "17"}, json={}))
    with pytest.raises(CloudRateLimitError) as exc:
        await client.get("/v1/hosts")
    d = exc.value.to_dict()
    assert d["retry_after_seconds"] == 17 and d["rate_limited"] is True
    assert "17" in d["message"]


@respx.mock
async def test_rate_limit_without_header(client):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(429, text="slow down"))
    with pytest.raises(CloudRateLimitError) as exc:
        await client.get("/v1/hosts")
    assert exc.value.retry_after is None
    assert "retry_after_seconds" not in exc.value.to_dict()


@respx.mock
async def test_rate_limit_bad_header(client):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct"}))
    with pytest.raises(CloudRateLimitError) as exc:
        await client.get("/v1/hosts")
    assert exc.value.retry_after is None


@respx.mock
async def test_timeout_and_connect_errors(client):
    respx.get(f"{BASE}/v1/a").mock(side_effect=httpx.ReadTimeout("t"))
    respx.get(f"{BASE}/v1/b").mock(side_effect=httpx.ConnectError("c"))
    with pytest.raises(UnifiError, match="Timed out"):
        await client.get("/v1/a")
    with pytest.raises(UnifiError) as exc:
        await client.get("/v1/b")
    assert exc.value.category == ErrorCategory.CONNECTION_ERROR


@respx.mock
async def test_non_json_body(client):
    respx.get(f"{BASE}/v1/hosts").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(UnifiError) as exc:
        await client.get("/v1/hosts")
    assert exc.value.category == ErrorCategory.UNEXPECTED_RESPONSE
