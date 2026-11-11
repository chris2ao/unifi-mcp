import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.tools._registry import PRODUCT_PROBES
from unifi_mcp.tools.network import integration_devices as idev

BASE = "https://192.0.2.1"
SITE_UUID = "00000000-0000-0000-0000-0000000000a1"
SITES = f"{BASE}/proxy/network/integration/v1/sites"
DEVICES = f"{SITES}/{SITE_UUID}/devices"
AP_ID = "11111111-0000-0000-0000-000000000001"
SW_ID = "11111111-0000-0000-0000-000000000002"

AP = {"id": AP_ID, "name": "Office AP", "model": "U7 Pro", "macAddress": "60:22:32:9b:0e:09",
      "ipAddress": "192.0.2.10", "state": "ONLINE", "firmwareVersion": "8.0.1",
      "features": ["accessPoint"], "interfaces": ["radios"]}
SWITCH = {"id": SW_ID, "name": "Core Switch", "model": "USW-24", "macAddress": "60:22:32:00:00:02",
          "ipAddress": "192.0.2.2", "state": "ONLINE", "firmwareVersion": "7.1.0",
          "features": ["switching"], "interfaces": ["ports"]}
RADIOS = [{"frequencyGHz": 5, "channel": 36, "channelWidthMHz": 80, "wlanStandard": "802.11ax"}]
DETAIL = {**AP, "adoptedAt": "2026-01-01T00:00:00Z", "provisionedAt": "2026-01-02T00:00:00Z",
          "interfaces": {"radios": RADIOS}}
STATS = {"uptimeSec": 3600, "cpuUtilizationPct": 12.5, "memoryUtilizationPct": 40.0,
         "loadAverage1Min": 0.3, "uplink": {"txRateBps": 1000}, "lastHeartbeatAt": "2026-01-03T00:00:00Z",
         "interfaces": {"radios": [{"frequencyGHz": 5, "txRetriesPct": 4.2}]}}


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def mock_sites():
    respx.get(SITES).mock(return_value=httpx.Response(
        200, json={"data": [{"id": SITE_UUID, "internalReference": "default", "name": "Default"}]}))


def mock_devices(*devices):
    respx.get(DEVICES).mock(return_value=httpx.Response(
        200, json={"offset": 0, "limit": 100, "count": len(devices), "totalCount": len(devices),
                   "data": list(devices)}))


def test_module_declarations():
    assert idev.GROUP == "integration"
    assert idev.TIER2_TOOLS == {}
    assert [t.__name__ for t in idev.TOOLS] == [
        "integration_list_sites", "integration_list_devices", "integration_get_device",
        "integration_get_device_stats", "integration_get_ap_radios"]


def test_network_probe_uses_the_integration_api():
    assert PRODUCT_PROBES["network"] == "/proxy/network/integration/v1/info"


@respx.mock
@pytest.mark.asyncio
async def test_list_sites(mock_client):
    mock_sites()
    assert await idev.integration_list_sites(mock_client) == [
        {"id": SITE_UUID, "internal_reference": "default", "name": "Default"}]


@respx.mock
@pytest.mark.asyncio
async def test_list_devices_summarizes(mock_client):
    mock_sites()
    mock_devices(AP, SWITCH)
    devices = await idev.integration_list_devices(mock_client)
    assert [d["name"] for d in devices] == ["Office AP", "Core Switch"]
    assert devices[0] == {"id": AP_ID, "name": "Office AP", "model": "U7 Pro", "mac": "60:22:32:9b:0e:09",
                          "ip": "192.0.2.10", "state": "ONLINE", "firmware": "8.0.1",
                          "features": ["accessPoint"], "interfaces": ["radios"]}


@respx.mock
@pytest.mark.asyncio
async def test_list_devices_follows_pages(mock_client):
    mock_sites()
    route = respx.get(DEVICES)
    route.side_effect = [
        httpx.Response(200, json={"totalCount": 2, "data": [AP]}),
        httpx.Response(200, json={"totalCount": 2, "data": [SWITCH]}),
    ]
    devices = await idev.integration_list_devices(mock_client)
    assert [d["id"] for d in devices] == [AP_ID, SW_ID]
    assert [c.request.url.params["offset"] for c in route.calls] == ["0", "1"]


@respx.mock
@pytest.mark.asyncio
async def test_list_devices_stops_without_total(mock_client):
    mock_sites()
    route = respx.get(DEVICES).mock(return_value=httpx.Response(200, json={"data": [AP]}))
    assert len(await idev.integration_list_devices(mock_client)) == 1
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_get_device_by_id(mock_client):
    mock_sites()
    respx.get(f"{DEVICES}/{AP_ID}").mock(return_value=httpx.Response(200, json=DETAIL))
    r = await idev.integration_get_device(mock_client, device_id=AP_ID)
    assert r["radios"] == RADIOS
    assert r["adopted_at"] == "2026-01-01T00:00:00Z"
    assert r["mac"] == "60:22:32:9b:0e:09"


@respx.mock
@pytest.mark.asyncio
async def test_get_device_by_mac(mock_client):
    mock_sites()
    mock_devices(SWITCH, AP)
    respx.get(f"{DEVICES}/{AP_ID}").mock(return_value=httpx.Response(200, json=DETAIL))
    r = await idev.integration_get_device(mock_client, mac="60-22-32-9B-0E-09")
    assert r["id"] == AP_ID


@pytest.mark.asyncio
async def test_get_device_needs_id_or_mac(mock_client):
    with pytest.raises(UnifiError) as err:
        await idev.integration_get_device(mock_client)
    assert err.value.category == ErrorCategory.VALIDATION_ERROR


@pytest.mark.asyncio
async def test_get_device_rejects_a_malformed_mac(mock_client):
    with pytest.raises(UnifiError) as err:
        await idev.integration_get_device(mock_client, mac="not-a-mac")
    assert err.value.category == ErrorCategory.VALIDATION_ERROR


@respx.mock
@pytest.mark.asyncio
async def test_get_device_unknown_mac(mock_client):
    mock_sites()
    mock_devices(SWITCH)
    with pytest.raises(UnifiError) as err:
        await idev.integration_get_device(mock_client, mac="60:22:32:9b:0e:09")
    assert err.value.category == ErrorCategory.NOT_FOUND


@respx.mock
@pytest.mark.asyncio
async def test_get_device_stats(mock_client):
    mock_sites()
    respx.get(f"{DEVICES}/{AP_ID}/statistics/latest").mock(return_value=httpx.Response(200, json=STATS))
    r = await idev.integration_get_device_stats(mock_client, device_id=AP_ID)
    assert r == {"device_id": AP_ID, "uptime_sec": 3600, "cpu_pct": 12.5, "memory_pct": 40.0,
                 "load_1m": 0.3, "uplink": {"txRateBps": 1000},
                 "radios": [{"frequencyGHz": 5, "txRetriesPct": 4.2}],
                 "last_heartbeat_at": "2026-01-03T00:00:00Z"}


@respx.mock
@pytest.mark.asyncio
async def test_ap_radios_covers_access_points_only(mock_client):
    mock_sites()
    mock_devices(AP, SWITCH)
    respx.get(f"{DEVICES}/{AP_ID}").mock(return_value=httpx.Response(200, json=DETAIL))
    respx.get(f"{DEVICES}/{AP_ID}/statistics/latest").mock(return_value=httpx.Response(200, json=STATS))
    r = await idev.integration_get_ap_radios(mock_client)
    assert len(r) == 1
    assert r[0]["name"] == "Office AP"
    assert r[0]["radios_config"] == RADIOS
    assert r[0]["radios_stats"] == [{"frequencyGHz": 5, "txRetriesPct": 4.2}]


@respx.mock
@pytest.mark.asyncio
async def test_ap_radios_reports_a_failing_device(mock_client):
    mock_sites()
    mock_devices(AP)
    respx.get(f"{DEVICES}/{AP_ID}").mock(return_value=httpx.Response(404, json={"message": "gone"}))
    r = await idev.integration_get_ap_radios(mock_client)
    assert r[0]["name"] == "Office AP"
    assert "error" in r[0]
