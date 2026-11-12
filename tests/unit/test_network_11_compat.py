"""UniFi Network 11 compatibility (shapes verified read-only against Network 11.0.99).

Covers the Integration API `reportFlowEnabled` firewall policy field, the
Network 11 aggregated-dashboard layout, the empty legacy site report, and the
device radio `txPowerMode` field.
"""

import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.network import device_ops, insights, site_insights
from unifi_mcp.tools.network import zbf_official as zo
from unifi_mcp.tools.network import zbf_policies_official as zp

FIXTURES = Path(__file__).parent.parent / "fixtures"
SITE_UUID = "00000000-0000-0000-0000-000000000001"
HOST = "https://192.168.1.1"
FW = f"{HOST}/proxy/network/integration/v1/sites/{SITE_UUID}/firewall/policies"
DASH = f"{HOST}/proxy/network/v2/api/site/default/aggregated-dashboard"
REPORT = f"{HOST}/proxy/network/api/s/default/stat/report/hourly.site"
DEVICES = f"{HOST}/proxy/network/integration/v1/sites/{SITE_UUID}/devices"
POLICY = "00000000-0000-0000-0000-0000000000c1"
DEV_ID = "00000000-0000-0000-0000-0000000000a1"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", HOST)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    client = UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def fx(name: str):
    return json.loads((FIXTURES / name).read_text())


def _policy11(**overrides) -> dict:
    """A user-defined policy in the Network 11.0.99 Integration API shape."""
    policy = {
        "id": POLICY, "enabled": True, "name": "Block IoT to Internal", "index": 10010,
        "action": {"type": "BLOCK"},
        "source": {"zoneId": "00000000-0000-0000-0000-0000000000a1"},
        "destination": {"zoneId": "00000000-0000-0000-0000-0000000000a3"},
        "ipProtocolScope": {"ipVersion": "IPV4_AND_IPV6"},
        "connectionStateFilter": ["NEW", "INVALID"],
        "loggingEnabled": False,
        "reportFlowEnabled": True,
        "metadata": {"origin": "USER_DEFINED"},
    }
    return policy | overrides


# --- reportFlowEnabled ---------------------------------------------------------


def test_put_body_keeps_report_flow_enabled():
    assert zo._put_body(_policy11())["reportFlowEnabled"] is True
    assert "reportFlowEnabled" not in zo._put_body(_policy11(reportFlowEnabled=None))


def test_format_policy_reports_flow_flag_and_none_on_older_firmware():
    assert zo._format_policy(_policy11())["report_flow_enabled"] is True
    older = {k: v for k, v in _policy11().items() if k != "reportFlowEnabled"}
    assert zo._format_policy(older)["report_flow_enabled"] is None


@respx.mock
async def test_toggle_preserves_report_flow_enabled(mock_client):
    respx.get(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json=_policy11()))
    put = respx.put(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json={"id": POLICY}))
    r = await zo.toggle_zbf_policy(mock_client, POLICY, False, confirm=True)
    assert r["executed"] is True
    body = json.loads(put.calls[0].request.content)
    assert body["enabled"] is False and body["reportFlowEnabled"] is True


@respx.mock
async def test_update_preserves_report_flow_enabled_when_not_passed(mock_client):
    respx.get(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json=_policy11()))
    put = respx.put(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json={"id": POLICY}))
    r = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, name="Renamed", confirm=True)
    assert r["executed"] is True and r["changed_fields"] == ["name"]
    assert json.loads(put.calls[0].request.content)["reportFlowEnabled"] is True


@respx.mock
async def test_update_sets_report_flow(mock_client):
    respx.get(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json=_policy11()))
    put = respx.put(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json={"id": POLICY}))
    preview = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, report_flow=False)
    assert preview["preview"] is True and preview["changed_fields"] == ["reportFlowEnabled"]
    assert preview["after"]["reportFlowEnabled"] is False and not put.called
    r = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, report_flow=False, confirm=True)
    assert r["executed"] is True
    assert json.loads(put.calls[0].request.content)["reportFlowEnabled"] is False


async def test_update_rejects_non_bool_report_flow(mock_client):
    r = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, report_flow="yes")
    assert r["error"] is True and "report_flow" in r["message"]


async def test_update_same_report_flow_is_no_change(mock_client):
    with respx.mock:
        respx.get(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json=_policy11()))
        r = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, report_flow=True)
    assert r["error"] is True and "No changes" in r["message"]


async def test_create_sends_report_flow_only_when_passed(mock_client):
    zone_a, zone_b = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a3"
    default = await zp.create_zbf_policy_v1(mock_client, name="P", source_zone_id=zone_a, destination_zone_id=zone_b)
    assert "reportFlowEnabled" not in default["body"]
    explicit = await zp.create_zbf_policy_v1(
        mock_client, name="P", source_zone_id=zone_a, destination_zone_id=zone_b, report_flow=True,
    )
    assert explicit["body"]["reportFlowEnabled"] is True
    bad = await zp.create_zbf_policy_v1(
        mock_client, name="P", source_zone_id=zone_a, destination_zone_id=zone_b, report_flow=1,
    )
    assert bad["error"] is True and "report_flow" in bad["message"]


@respx.mock
async def test_toggle_confirm_refused_when_report_flow_changed_after_preview(mock_client):
    route = respx.get(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json=_policy11()))
    put = respx.put(f"{FW}/{POLICY}")
    assert (await zo.toggle_zbf_policy(mock_client, POLICY, False))["preview"] is True
    route.mock(return_value=httpx.Response(200, json=_policy11(reportFlowEnabled=False)))
    r = await zo.toggle_zbf_policy(mock_client, POLICY, False, confirm=True)
    assert r["error"] is True and r["category"] == "CONFLICT" and not put.called


# --- Network 11 dashboard --------------------------------------------------------


@respx.mock
async def test_dashboard_network11_layout(mock_client):
    respx.get(DASH).mock(return_value=httpx.Response(200, json=fx("insights_dashboard_v11.json")))
    r = await insights.get_dashboard_summary(mock_client)
    assert r["most_active_aps"] == [{
        "name": "Office AP", "model": "U7PRO", "mac": "aa:bb:cc:00:00:01",
        "bytes_total": 5000, "satisfaction": 97,
    }]
    assert r["wifi_connectivity"] == []
    assert r["radio_activity"] == [
        {"band": "ng", "avg_total_cu_pct": 41.5, "avg_self_cu_pct": 10.0,
         "avg_interf_cu_pct": 31.5, "mcast_bcast_total_pct": 2.5},
        {"band": "na", "avg_total_cu_pct": 12.0, "avg_self_cu_pct": 8.0,
         "avg_interf_cu_pct": 4.0, "mcast_bcast_total_pct": 0.5},
    ]
    assert r["radio_access_points"] == 2


@respx.mock
async def test_dashboard_prefers_legacy_ap_section_when_present(mock_client):
    respx.get(DASH).mock(return_value=httpx.Response(200, json=fx("insights_dashboard.json")))
    r = await insights.get_dashboard_summary(mock_client)
    assert r["most_active_aps"] and r["radio_activity"] == [] and r["radio_access_points"] == 0


@respx.mock
async def test_dashboard_hours_window_sends_start_and_end(mock_client, monkeypatch):
    monkeypatch.setattr(insights.time, "time", lambda: 1_800_000_000.0)
    route = respx.get(DASH).mock(return_value=httpx.Response(200, json=fx("insights_dashboard_v11.json")))
    await insights.get_dashboard_summary(mock_client, hours=6)
    params = route.calls[0].request.url.params
    assert params["end"] == "1800000000000"
    assert params["start"] == str(1_800_000_000_000 - 6 * 3_600_000)


@respx.mock
async def test_dashboard_default_sends_no_window(mock_client):
    route = respx.get(DASH).mock(return_value=httpx.Response(200, json=fx("insights_dashboard_v11.json")))
    await insights.get_dashboard_summary(mock_client)
    assert "start" not in route.calls[0].request.url.params


@pytest.mark.parametrize("hours", [0, 721, 1.5, True, "6"])
async def test_dashboard_hours_validation(mock_client, hours):
    r = await insights.get_dashboard_summary(mock_client, hours=hours)
    assert r["error"] is True and "hours" in r["message"]


# --- legacy site report on Network 11 ----------------------------------------------


@respx.mock
async def test_empty_site_report_explains_network11(mock_client):
    respx.post(REPORT).mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []}))
    r = await site_insights.get_site_traffic_history(mock_client)
    assert r["count"] == 0 and r["rows"] == []
    assert "Network 11" in r["note"] and "get_dashboard_summary" in r["note"]


@respx.mock
async def test_site_report_with_rows_has_no_note(mock_client):
    respx.post(REPORT).mock(return_value=httpx.Response(200, json=fx("site_insights_report_hourly.json")))
    r = await site_insights.get_site_traffic_history(mock_client)
    assert r["count"] > 0 and "note" not in r


# --- device radios -------------------------------------------------------------------


@respx.mock
async def test_device_details_include_tx_power_mode(mock_client):
    detail = {
        "id": DEV_ID, "macAddress": "aa:bb:cc:00:00:01", "name": "AP", "model": "U7PRO",
        "interfaces": {"radios": [
            {"wlanStandard": "802.11be", "frequencyGHz": 6, "channel": 37,
             "channelWidthMHz": 160, "txPowerMode": "AUTO"},
            {"wlanStandard": "802.11ah", "frequencyGHz": 0.9, "channel": 1, "channelWidthMHz": 1},
        ]},
    }
    respx.get(f"{DEVICES}/{DEV_ID}").mock(return_value=httpx.Response(200, json=detail))
    r = await device_ops.get_device_details_v1(mock_client, DEV_ID)
    assert r["radios"][0]["tx_power_mode"] == "AUTO"
    assert r["radios"][1] == {
        "wlan_standard": "802.11ah", "frequency_ghz": 0.9, "channel": 1,
        "channel_width_mhz": 1, "tx_power_mode": None,
    }


async def test_update_report_flow_refused_on_console_without_the_field(mock_client):
    older = {k: v for k, v in _policy11().items() if k != "reportFlowEnabled"}
    with respx.mock:
        respx.get(f"{FW}/{POLICY}").mock(return_value=httpx.Response(200, json=older))
        put = respx.put(f"{FW}/{POLICY}")
        r = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, report_flow=True, confirm=True)
    assert r["error"] is True and "Network 11" in r["message"] and not put.called


@respx.mock
async def test_dashboard_names_are_cleaned(mock_client):
    data = fx("insights_dashboard_v11.json")
    data["most_active_clients"]["usage_by_client"][0]["display_name"] = "Lap\x1btop"
    respx.get(DASH).mock(return_value=httpx.Response(200, json=data))
    r = await insights.get_dashboard_summary(mock_client)
    assert r["most_active_clients"][0]["name"] == "Laptop"
