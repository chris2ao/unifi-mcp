import httpx
import pytest
import respx

from unifi_mcp.cloud.client import CloudClient
from unifi_mcp.cloud.config import CloudConfig
from unifi_mcp.errors import UnifiError
from unifi_mcp.tools.cloud import all_cloud_tools, hosts, isp_metrics, sdwan
import json
from pathlib import Path


def load_fixture(name: str) -> dict:
    return json.loads((Path(__file__).parent.parent / "fixtures" / name).read_text())

BASE = "https://api.ui.com"
HOST = "00000000000000000000000000000001:111111111"


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "k")
    c = CloudClient(CloudConfig())
    yield c
    await c.close()


def test_module_conventions():
    names = [t.__name__ for t in all_cloud_tools()]
    assert len(names) == 9 and len(set(names)) == 9
    for mod in (hosts, isp_metrics, sdwan):
        assert mod.GROUP == "cloud" and mod.TIER2_TOOLS == {}
    for t in all_cloud_tools():
        assert t.__doc__ and "\u2014" not in t.__doc__


@respx.mock
async def test_list_hosts_paginates(client):
    respx.get(f"{BASE}/v1/hosts").mock(side_effect=[
        httpx.Response(200, json=load_fixture("cloud/hosts.json")),
        httpx.Response(200, json=load_fixture("cloud/hosts_page2.json")),
    ])
    assert len(await hosts.list_cloud_hosts(client)) == 2


@respx.mock
async def test_get_host(client):
    respx.get(f"{BASE}/v1/hosts/{HOST}").mock(
        return_value=httpx.Response(200, json={"data": load_fixture("cloud/hosts.json")["data"][0]}))
    assert (await hosts.get_cloud_host(client, HOST))["type"] == "console"


@respx.mock
async def test_get_host_shapes_and_not_found(client):
    respx.get(f"{BASE}/v1/hosts/a").mock(return_value=httpx.Response(200, json={"data": [{"id": "a"}]}))
    respx.get(f"{BASE}/v1/hosts/b").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE}/v1/hosts/c").mock(return_value=httpx.Response(404, json={"message": "x"}))
    assert (await hosts.get_cloud_host(client, "a"))["id"] == "a"
    missing = await hosts.get_cloud_host(client, "b")
    assert missing["error"] and missing["category"] == "NOT_FOUND"
    with pytest.raises(UnifiError):
        await hosts.get_cloud_host(client, "c")


@pytest.mark.parametrize("bad", ["", ".", "a/b", "..", "a..b", "-x", "a?b", "a#b", "a b", None, 5])
async def test_id_validation(client, bad):
    for fn, kw in ((hosts.get_cloud_host, "host_id"), (sdwan.get_sdwan_config, "config_id"),
                   (sdwan.get_sdwan_status, "config_id")):
        r = await fn(client, **{kw: bad})
        assert r["error"] and r["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_list_sites(client):
    respx.get(f"{BASE}/v1/sites").mock(return_value=httpx.Response(200, json=load_fixture("cloud/sites.json")))
    assert (await hosts.list_cloud_sites(client))[0]["permission"] == "admin"


@respx.mock
async def test_list_devices_filters(client):
    route = respx.get(f"{BASE}/v1/devices").mock(return_value=httpx.Response(200, json=load_fixture("cloud/devices.json")))
    out = await hosts.list_cloud_devices(client, host_ids=[HOST])
    assert out[0]["devices"][0]["name"] == "Office AP"
    assert "hostIds%5B%5D=" in str(route.calls[0].request.url) or "hostIds[]=" in str(route.calls[0].request.url)
    await hosts.list_cloud_devices(client)
    assert "hostIds" not in str(route.calls[1].request.url)


@pytest.mark.parametrize("bad", [[], "x", ["a/b"], [1]])
async def test_list_devices_validation(client, bad):
    assert (await hosts.list_cloud_devices(client, host_ids=bad))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_get_isp_metrics_duration(client):
    route = respx.get(f"{BASE}/v1/isp-metrics/1h").mock(
        return_value=httpx.Response(200, json=load_fixture("cloud/isp_metrics.json")))
    out = await isp_metrics.get_isp_metrics(client, "1h", duration="7d")
    assert out[0]["periods"][0]["data"]["wan"]["avgLatency"] == 12
    assert route.calls[0].request.url.params["duration"] == "7d"


@respx.mock
async def test_get_isp_metrics_range_default(client):
    route = respx.get(f"{BASE}/v1/isp-metrics/5m").mock(return_value=httpx.Response(200, json={"data": []}))
    assert await isp_metrics.get_isp_metrics(client, begin="2026-06-15T00:00:00Z", end="2026-06-15T01:00:00Z") == []
    p = route.calls[0].request.url.params
    assert p["beginTimestamp"] and p["endTimestamp"] and "duration" not in p


@pytest.mark.parametrize("kw", [
    {"metric_type": "1d"}, {"duration": "7d"}, {"metric_type": "1h", "duration": "24h"},
    {"duration": "24h", "begin": "2026-06-15T00:00:00Z"}, {"begin": "yesterday"}, {"end": 5},
])
async def test_get_isp_metrics_validation(client, kw):
    assert (await isp_metrics.get_isp_metrics(client, **kw))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_query_isp_metrics(client):
    route = respx.post(f"{BASE}/v1/isp-metrics/1h/query").mock(
        return_value=httpx.Response(200, json=load_fixture("cloud/isp_query.json")))
    sites = [{"hostId": HOST, "siteId": "s1", "beginTimestamp": "2026-06-15T00:00:00Z", "junk": 1}]
    out = await isp_metrics.query_isp_metrics(client, "1h", sites)
    assert out["status"] == "partialSuccess" and len(out["metrics"]) == 1
    assert route.calls[0].request.content == (
        b'{"sites":[{"hostId":"%s","siteId":"s1","beginTimestamp":"2026-06-15T00:00:00Z"}]}' % HOST.encode())
    assert "junk" in sites[0]  # input not mutated


@respx.mock
async def test_query_isp_metrics_odd_shape(client):
    respx.post(f"{BASE}/v1/isp-metrics/5m/query").mock(return_value=httpx.Response(200, json={"data": None}))
    assert await isp_metrics.query_isp_metrics(client, "5m", [{"hostId": "h", "siteId": "s"}]) == {"metrics": []}


@pytest.mark.parametrize("mt,sites", [
    ("2m", [{"hostId": "h", "siteId": "s"}]), ("5m", []), ("5m", "x"), ("5m", ["x"]),
    ("5m", [{"hostId": "h"}]), ("5m", [{"hostId": "h", "siteId": "s", "endTimestamp": "bad"}]),
])
async def test_query_isp_metrics_validation(client, mt, sites):
    assert (await isp_metrics.query_isp_metrics(client, mt, sites))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_sdwan(client):
    respx.get(f"{BASE}/v1/sd-wan-configs").mock(return_value=httpx.Response(200, json=load_fixture("cloud/sdwan_configs.json")))
    respx.get(f"{BASE}/v1/sd-wan-configs/sdwan-0001").mock(
        return_value=httpx.Response(200, json={"data": load_fixture("cloud/sdwan_configs.json")["data"][0]}))
    respx.get(f"{BASE}/v1/sd-wan-configs/sdwan-0001/status").mock(
        return_value=httpx.Response(200, json=load_fixture("cloud/sdwan_status.json")))
    assert (await sdwan.list_sdwan_configs(client))[0]["name"] == "Branch Mesh"
    assert (await sdwan.get_sdwan_config(client, "sdwan-0001"))["type"] == "sdwan-hbsp"
    assert (await sdwan.get_sdwan_status(client, "sdwan-0001"))["hubs"][0]["name"] == "Hub A"


@respx.mock
async def test_sdwan_empty(client):
    respx.get(f"{BASE}/v1/sd-wan-configs").mock(return_value=httpx.Response(200, json={"data": []}))
    respx.get(f"{BASE}/v1/sd-wan-configs/x/status").mock(return_value=httpx.Response(200, json={"data": None}))
    respx.get(f"{BASE}/v1/sd-wan-configs/x").mock(return_value=httpx.Response(200, json={"data": None}))
    assert await sdwan.list_sdwan_configs(client) == []
    assert await sdwan.get_sdwan_status(client, "x") == {}
    assert await sdwan.get_sdwan_config(client, "x") == {}


@pytest.mark.parametrize("bad", ["2026-06-15", "2026-06-15T10:00:00", "nope"])
def test_timestamp_requires_rfc3339_with_offset(bad):
    from unifi_mcp.tools.cloud._common import check_timestamp

    assert check_timestamp(bad, "begin")["category"] == "VALIDATION_ERROR"


def test_timestamp_accepts_rfc3339():
    from unifi_mcp.tools.cloud._common import check_timestamp

    assert check_timestamp("2026-06-15T10:00:00Z", "begin") is None
    assert check_timestamp("2026-06-15T10:00:00+02:00", "begin") is None
