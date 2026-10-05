import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.network import device_ops
from unifi_mcp.tools.network.device_ops import (
    TIER2_TOOLS,
    get_device_details_v1,
    get_device_statistics,
    list_pending_devices,
    power_cycle_port,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
SITE_UUID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    client = UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


BASE = "https://192.168.1.1/proxy/network/integration/v1"
DEV_ID = "00000000-0000-0000-0000-0000000000a1"
DEV_URL = f"{BASE}/sites/{SITE_UUID}/devices/{DEV_ID}"
LIST_URL = f"{BASE}/sites/{SITE_UUID}/devices"
STA_URL = "https://192.168.1.1/proxy/network/api/s/default/stat/sta"
MAC = "aa:bb:cc:00:00:01"


def test_module_declarations():
    assert device_ops.GROUP == "core"
    assert TIER2_TOOLS == {"power_cycle_port": "devices"}
    assert len(device_ops.TOOLS) == 4


@respx.mock
async def test_statistics_by_id(mock_client):
    respx.get(f"{DEV_URL}/statistics/latest").mock(
        return_value=httpx.Response(200, json=load_fixture("device_ops_statistics.json"))
    )
    r = await get_device_statistics(mock_client, DEV_ID)
    assert r["cpu_pct"] == 12.5
    assert r["memory_pct"] == 40.1
    assert r["load_average"] == {"1m": 1.5, "5m": 1.2, "15m": 1.0}
    assert r["uplink"] == {"tx_bps": 1000, "rx_bps": 2000}
    assert r["uptime"] == "1d 2h 3m"
    assert r["radios"][0] == {"frequency_ghz": 5, "tx_retries_pct": 3.2}


@respx.mock
async def test_statistics_by_mac_uses_filter(mock_client):
    route = respx.get(LIST_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("device_ops_list.json"))
    )
    respx.get(f"{DEV_URL}/statistics/latest").mock(
        return_value=httpx.Response(200, json=load_fixture("device_ops_statistics.json"))
    )
    r = await get_device_statistics(mock_client, "AA-BB-CC-00-00-01")
    assert r["device_id"] == DEV_ID
    assert route.calls[0].request.url.params["filter"] == f"macAddress.eq('{MAC}')"


@respx.mock
async def test_statistics_empty_interfaces_and_missing_fields(mock_client):
    respx.get(f"{DEV_URL}/statistics/latest").mock(
        return_value=httpx.Response(200, json={"uptimeSec": 5, "interfaces": {}})
    )
    r = await get_device_statistics(mock_client, DEV_ID)
    assert r["radios"] == []
    assert r["cpu_pct"] is None


@respx.mock
async def test_statistics_unknown_mac_not_found(mock_client):
    respx.get(LIST_URL).mock(return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    r = await get_device_statistics(mock_client, MAC)
    assert r["error"] and r["category"] == "NOT_FOUND"


@respx.mock
async def test_statistics_404_not_found(mock_client):
    respx.get(f"{DEV_URL}/statistics/latest").mock(return_value=httpx.Response(404))
    r = await get_device_statistics(mock_client, DEV_ID)
    assert r["category"] == "NOT_FOUND"


@respx.mock
async def test_statistics_empty_body_not_found(mock_client):
    respx.get(f"{DEV_URL}/statistics/latest").mock(return_value=httpx.Response(200, json={"data": []}))
    r = await get_device_statistics(mock_client, DEV_ID)
    assert r["category"] == "NOT_FOUND"


@respx.mock
async def test_statistics_server_error_propagates(mock_client):
    from unifi_mcp.errors import UnifiError

    respx.get(f"{DEV_URL}/statistics/latest").mock(return_value=httpx.Response(401))
    with pytest.raises(UnifiError):
        await get_device_statistics(mock_client, DEV_ID)


@pytest.mark.parametrize("bad", ["", "a/b", "../x", "id?x=1", "has space", None, "x#y"])
async def test_invalid_device_rejected(mock_client, bad):
    for fn in (get_device_statistics, get_device_details_v1):
        r = await fn(mock_client, bad)
        assert r["error"] and r["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_details_formatting(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    r = await get_device_details_v1(mock_client, DEV_ID)
    assert r["name"] == "Office Switch"
    assert r["features"] == ["switching"]
    assert r["firmware"] == {"version": "2.1.0", "updatable": False}
    assert r["provisioning"]["configuration_id"] == "cfg0001"
    assert r["uplink_device_id"] == "00000000-0000-0000-0000-0000000000a2"
    assert r["ports"][0]["poe"]["standard"] == "802.3bt"
    assert "poe" not in r["ports"][2]


@respx.mock
async def test_details_shape_variance_wrapped_and_radios(mock_client):
    d = {"id": DEV_ID, "features": {"accessPoint": None, "switching": None},
         "interfaces": {"radios": [{"wlanStandard": "802.11be", "frequencyGHz": 6, "channel": 5, "channelWidthMHz": 160}]}}
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json={"data": [d]}))
    r = await get_device_details_v1(mock_client, DEV_ID)
    assert r["features"] == ["accessPoint", "switching"]
    assert r["lags"] == []
    assert r["radios"][0]["channel"] == 5


@respx.mock
async def test_details_404(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(404))
    r = await get_device_details_v1(mock_client, DEV_ID)
    assert r["category"] == "NOT_FOUND"


@respx.mock
async def test_details_500_propagates(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(409))
    from unifi_mcp.errors import UnifiError

    with pytest.raises(UnifiError):
        await get_device_details_v1(mock_client, DEV_ID)


@respx.mock
async def test_details_empty_object(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    r = await get_device_details_v1(mock_client, DEV_ID)
    assert r["category"] == "NOT_FOUND"


@respx.mock
async def test_list_pending_devices(mock_client):
    respx.get(f"{BASE}/pending-devices").mock(
        return_value=httpx.Response(200, json=load_fixture("device_ops_pending.json"))
    )
    r = await list_pending_devices(mock_client)
    assert len(r) == 1
    assert r[0]["mac"] == "aa:bb:cc:00:00:99"
    assert r[0]["adoption_target_site_ids"] == ["00000000-0000-0000-0000-000000000001"]


@respx.mock
async def test_list_pending_devices_empty(mock_client):
    respx.get(f"{BASE}/pending-devices").mock(return_value=httpx.Response(200, json={"data": [], "totalCount": 0}))
    assert await list_pending_devices(mock_client) == []


@respx.mock
async def test_power_cycle_preview(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    respx.get(STA_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_stations.json")))
    post = respx.post(f"{DEV_URL}/interfaces/ports/2/actions")
    r = await power_cycle_port(mock_client, DEV_ID, 2)
    assert r["preview"] is True
    assert r["action"] == "power_cycle_port"
    assert r["connected"] == "Garage Camera"
    assert "reboot" in r["impact"] and "lose power" in r["impact"]
    assert not post.called
    again = await power_cycle_port(mock_client, DEV_ID, 2)
    assert again == r


@respx.mock
async def test_power_cycle_preview_station_lookup_fails(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    respx.get(STA_URL).mock(return_value=httpx.Response(500))
    r = await power_cycle_port(mock_client, DEV_ID, 1)
    assert r["preview"] is True
    assert r["connected"] is None


@respx.mock
async def test_power_cycle_preview_no_matching_station(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    respx.get(STA_URL).mock(return_value=httpx.Response(200, json=[]))
    r = await power_cycle_port(mock_client, DEV_ID, 1)
    assert r["connected"] is None


@respx.mock
async def test_power_cycle_preview_port_missing(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    r = await power_cycle_port(mock_client, DEV_ID, 42)
    assert r["category"] == "VALIDATION_ERROR"
    assert "does not exist" in r["message"]


@respx.mock
async def test_power_cycle_preview_not_poe(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    r = await power_cycle_port(mock_client, DEV_ID, 8)
    assert r["category"] == "VALIDATION_ERROR"
    assert "PoE" in r["message"]


@respx.mock
async def test_power_cycle_preview_device_missing(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(404))
    r = await power_cycle_port(mock_client, DEV_ID, 1)
    assert r["category"] == "NOT_FOUND"


@respx.mock
async def test_power_cycle_confirmed(mock_client):
    post = respx.post(f"{DEV_URL}/interfaces/ports/2/actions").mock(
        return_value=httpx.Response(200, json={})
    )
    r = await power_cycle_port(mock_client, DEV_ID, 2, confirm=True)
    assert r["executed"] is True and r["action"] == "power_cycle_port"
    assert json.loads(post.calls[0].request.content) == {"action": "POWER_CYCLE"}


@respx.mock
async def test_power_cycle_confirmed_by_mac(mock_client):
    respx.get(LIST_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_list.json")))
    post = respx.post(f"{DEV_URL}/interfaces/ports/1/actions").mock(return_value=httpx.Response(200, json={}))
    r = await power_cycle_port(mock_client, MAC, 1, confirm=True)
    assert r["executed"] is True
    assert post.called


@respx.mock
async def test_power_cycle_silent_noop(mock_client):
    respx.post(f"{DEV_URL}/interfaces/ports/2/actions").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    r = await power_cycle_port(mock_client, DEV_ID, 2, confirm=True)
    assert r["executed"] is False


@pytest.mark.parametrize("port", [0, -1, "2", 1.5, True, None])
async def test_power_cycle_bad_port(mock_client, port):
    r = await power_cycle_port(mock_client, DEV_ID, port)
    assert r["category"] == "VALIDATION_ERROR"


async def test_power_cycle_bad_device(mock_client):
    r = await power_cycle_port(mock_client, "a/b", 1)
    assert r["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_power_cycle_preview_warns_when_poe_down(mock_client):
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=load_fixture("device_ops_details.json")))
    respx.get(STA_URL).mock(return_value=httpx.Response(200, json=[]))
    r = await power_cycle_port(mock_client, DEV_ID, 1)
    assert r["preview"] is True and "DOWN" in r["warning"]
    ok = await power_cycle_port(mock_client, DEV_ID, 2)
    assert "warning" not in ok


@respx.mock
async def test_power_cycle_preview_rejects_poe_disabled(mock_client):
    details = load_fixture("device_ops_details.json")
    details["interfaces"]["ports"][1]["poe"]["enabled"] = False
    respx.get(DEV_URL).mock(return_value=httpx.Response(200, json=details))
    r = await power_cycle_port(mock_client, DEV_ID, 2)
    assert r["category"] == "VALIDATION_ERROR" and "disabled" in r["message"]
