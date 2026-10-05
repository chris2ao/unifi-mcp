import json

import httpx
import pytest
import respx

from tests.unit.test_network_traffic_rules import load_fixture
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig

BASE = "https://192.0.2.1/proxy/network"
CF = f"{BASE}/v2/api/site/default/content-filtering"
ROGUE = f"{BASE}/api/s/default/stat/rogueap"
REPORT = f"{BASE}/api/s/default/stat/report/{{}}.site"
VPN = f"{BASE}/v2/api/site/default/vpn/connections"
WG = f"{BASE}/v2/api/site/default/wireguard/users"
SCHED = f"{BASE}/api/s/default/rest/scheduletask"
DDNS = f"{BASE}/api/s/default/rest/dynamicdns"
SETTING = f"{BASE}/api/s/default/rest/setting"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.0.2.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def ok(name):
    return httpx.Response(200, json=load_fixture(name))


def test_module_conventions():
    from unifi_mcp.tools.network import site_insights as m

    assert m.GROUP == "insights"
    assert m.TIER2_TOOLS == {}
    assert len(m.TOOLS) == 7


def test_is_secret_key():
    from unifi_mcp.tools.network.site_insights import is_secret_key

    for k in ("x_password", "wifi_psk", "api_token", "secret_note", "admin_key", "Passphrase", "X_foo"):
        assert is_secret_key(k), k
    for k in ("name", "enabled", "ntp_server_1", "hostname"):
        assert not is_secret_key(k), k


def test_mask_secrets_keeps_booleans():
    from unifi_mcp.tools.network.site_insights import mask_secrets

    assert mask_secrets({"x_ssh_enabled": False, "x_ssh_password": "p"}) == {
        "x_ssh_enabled": False, "x_ssh_password": "***",
    }


def test_mask_secrets_does_not_mutate_and_keeps_empty():
    from unifi_mcp.tools.network.site_insights import mask_secrets

    src = {"a": {"x_password": "p"}, "b": [{"token": "t"}], "x_empty": "", "ok": 1}
    out = mask_secrets(src)
    assert out == {"a": {"x_password": "***"}, "b": [{"token": "***"}], "x_empty": "", "ok": 1}
    assert src["a"]["x_password"] == "p"


@respx.mock
async def test_list_content_filters(mock_client):
    from unifi_mcp.tools.network.site_insights import list_content_filters

    respx.get(CF).mock(return_value=ok("site_insights_content_filtering.json"))
    result = await list_content_filters(mock_client)
    assert result[0]["name"] == "Kids"
    assert result[0]["categories"] == ["ADULT", "GAMBLING"]
    assert result[0]["schedule"] == {"mode": "ALWAYS"}


@respx.mock
async def test_list_content_filters_404(mock_client):
    from unifi_mcp.tools.network.site_insights import list_content_filters

    respx.get(CF).mock(return_value=httpx.Response(404))
    result = await list_content_filters(mock_client)
    assert result["error"] is True and "content-filtering" in result["endpoint"]


@respx.mock
async def test_neighbor_aps_sorted_and_hides_own(mock_client):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    respx.get(ROGUE).mock(return_value=ok("site_insights_rogueap.json"))
    result = await list_neighbor_aps(mock_client)
    assert result["total_seen"] == 5
    assert result["matched"] == 4
    assert [n["ssid"] for n in result["neighbors"]] == ["Neighbor C", "Neighbor B", "Neighbor A", "Open Cafe"]
    assert all(n["is_ubnt"] is False for n in result["neighbors"])


@respx.mock
async def test_neighbor_aps_include_own_marks_ubnt(mock_client):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    respx.get(ROGUE).mock(return_value=ok("site_insights_rogueap.json"))
    result = await list_neighbor_aps(mock_client, include_own=True)
    assert result["neighbors"][0]["ssid"] == "Own Mesh"
    assert result["neighbors"][0]["is_ubnt"] is True


@respx.mock
async def test_neighbor_aps_filters(mock_client):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    respx.get(ROGUE).mock(return_value=ok("site_insights_rogueap.json"))
    r5 = await list_neighbor_aps(mock_client, band="5")
    assert [n["ssid"] for n in r5["neighbors"]] == ["Neighbor B"]
    r24 = await list_neighbor_aps(mock_client, band="2.4", min_rssi=-85)
    assert [n["ssid"] for n in r24["neighbors"]] == ["Neighbor C", "Neighbor A"]
    limited = await list_neighbor_aps(mock_client, limit=1)
    assert limited["returned"] == 1 and limited["matched"] == 4


@respx.mock
async def test_neighbor_aps_missing_rssi_sorts_last(mock_client):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    data = [{"essid": "NoSig", "band": "ng"}, {"essid": "Sig", "band": "ng", "rssi": -70}]
    respx.get(ROGUE).mock(return_value=httpx.Response(200, json=data))
    result = await list_neighbor_aps(mock_client)
    assert [n["ssid"] for n in result["neighbors"]] == ["Sig", "NoSig"]
    filtered = await list_neighbor_aps(mock_client, min_rssi=-80)
    assert [n["ssid"] for n in filtered["neighbors"]] == ["Sig"]


@respx.mock
async def test_neighbor_aps_prefers_signal_dbm_over_rssi(mock_client):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    data = [{"essid": "A", "band": "ng", "rssi": 49, "signal": -46}, {"essid": "B", "band": "ng", "rssi": 20, "signal": -75}]
    respx.get(ROGUE).mock(return_value=httpx.Response(200, json=data))
    result = await list_neighbor_aps(mock_client, min_rssi=-60)
    assert [(n["ssid"], n["rssi"]) for n in result["neighbors"]] == [("A", -46)]


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": 0}, {"limit": 5000}, {"limit": "x"}, {"limit": True}, {"band": "9"}, {"min_rssi": "loud"}],
)
async def test_neighbor_aps_validation(mock_client, kwargs):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    result = await list_neighbor_aps(mock_client, **kwargs)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_neighbor_aps_404(mock_client):
    from unifi_mcp.tools.network.site_insights import list_neighbor_aps

    respx.get(ROGUE).mock(return_value=httpx.Response(404))
    result = await list_neighbor_aps(mock_client)
    assert result["category"] == "NOT_FOUND" and result["endpoint"].endswith("stat/rogueap")


@respx.mock
async def test_traffic_history(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_traffic_history

    route = respx.post(REPORT.format("hourly")).mock(return_value=ok("site_insights_report_hourly.json"))
    result = await get_site_traffic_history(mock_client)
    assert result["interval"] == "hourly" and result["count"] == 2
    assert result["rows"][0] == {
        "time": 1700000000000, "wan_tx_bytes": 1000, "wan_rx_bytes": 5000, "bytes": None, "num_sta": 7,
    }
    body = json.loads(route.calls[0].request.content)
    assert "wan-rx_bytes" in body["attrs"] and "time" in body["attrs"]
    assert body["end"] - body["start"] == 24 * 3_600_000


@respx.mock
async def test_traffic_history_intervals(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_traffic_history

    for interval in ("5minutes", "daily"):
        route = respx.post(REPORT.format(interval)).mock(return_value=httpx.Response(200, json={"data": []}))
        result = await get_site_traffic_history(mock_client, interval=interval, hours=48)
        assert route.called and result["count"] == 0 and result["hours"] == 48


@pytest.mark.parametrize(
    "kwargs", [{"interval": "weekly"}, {"hours": 0}, {"hours": 9000}, {"hours": "6"}, {"hours": True}]
)
async def test_traffic_history_validation(mock_client, kwargs):
    from unifi_mcp.tools.network.site_insights import get_site_traffic_history

    result = await get_site_traffic_history(mock_client, **kwargs)
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_traffic_history_404(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_traffic_history

    respx.post(REPORT.format("hourly")).mock(return_value=httpx.Response(404))
    result = await get_site_traffic_history(mock_client)
    assert result["error"] is True and "hourly.site" in result["endpoint"]


@respx.mock
async def test_vpn_connections_masks_secrets(mock_client):
    from unifi_mcp.tools.network.site_insights import list_vpn_connections

    respx.get(VPN).mock(return_value=ok("site_insights_vpn_connections.json"))
    respx.get(WG).mock(return_value=ok("site_insights_wireguard_users.json"))
    result = await list_vpn_connections(mock_client)
    assert result["errors"] == []
    conn = result["connections"][0]
    assert conn["name"] == "Branch tunnel" and conn["status"] == "UP"
    assert conn["details"]["x_shared_secret"] == "***"
    assert conn["details"]["pre_shared_key"] == "***"
    user = result["wireguard_users"][0]
    assert user["name"] == "Phone"
    dumped = json.dumps(result)
    for leaked in ("PRIVKEY", "PSK", "hunter2", "hunter3"):
        assert leaked not in dumped


@respx.mock
async def test_vpn_connections_partial_failure(mock_client):
    from unifi_mcp.tools.network.site_insights import list_vpn_connections

    respx.get(VPN).mock(return_value=httpx.Response(404))
    respx.get(WG).mock(return_value=httpx.Response(200, json={"users": [{"id": "u", "name": "n"}]}))
    result = await list_vpn_connections(mock_client)
    assert result["connections"] == []
    assert result["wireguard_users"][0]["id"] == "u"
    assert len(result["errors"]) == 1 and "vpn/connections" in result["errors"][0]["endpoint"]


@respx.mock
async def test_vpn_connections_empty(mock_client):
    from unifi_mcp.tools.network.site_insights import list_vpn_connections

    respx.get(VPN).mock(return_value=httpx.Response(200, json={"connections": []}))
    respx.get(WG).mock(return_value=httpx.Response(200, json=[]))
    result = await list_vpn_connections(mock_client)
    assert result == {"connections": [], "wireguard_users": [], "errors": []}


@respx.mock
async def test_scheduled_tasks(mock_client):
    from unifi_mcp.tools.network.site_insights import list_scheduled_tasks

    respx.get(SCHED).mock(return_value=ok("site_insights_scheduletask.json"))
    result = await list_scheduled_tasks(mock_client)
    assert result[0]["name"] == "Nightly upgrade" and result[0]["cron_expr"] == "0 3 * * *"


@respx.mock
async def test_scheduled_tasks_404(mock_client):
    from unifi_mcp.tools.network.site_insights import list_scheduled_tasks

    respx.get(SCHED).mock(return_value=httpx.Response(404))
    assert (await list_scheduled_tasks(mock_client))["error"] is True


@respx.mock
async def test_dynamic_dns_masks_password_and_login_secrets(mock_client):
    from unifi_mcp.tools.network.site_insights import list_dynamic_dns

    respx.get(DDNS).mock(return_value=ok("site_insights_dynamicdns.json"))
    result = await list_dynamic_dns(mock_client)
    assert result[0]["host_name"] == "home.example.com"
    assert result[0]["x_password"] == "***"
    assert result[0]["password"] == "***"
    assert "s3cret" not in json.dumps(result)


@respx.mock
async def test_dynamic_dns_empty(mock_client):
    from unifi_mcp.tools.network.site_insights import list_dynamic_dns

    respx.get(DDNS).mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []}))
    assert await list_dynamic_dns(mock_client) == []


@respx.mock
async def test_settings_lists_section_keys(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    respx.get(SETTING).mock(return_value=ok("site_insights_settings.json"))
    result = await get_site_settings(mock_client)
    assert result == {"sections": ["guest_access", "mgmt", "ntp", "radius", "snmp"], "count": 5}
    assert "hunter" not in json.dumps(result)


@respx.mock
async def test_settings_section_masks_every_secret(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    respx.get(SETTING).mock(return_value=ok("site_insights_settings.json"))
    result = await get_site_settings(mock_client, section="mgmt")
    s = result["settings"]
    assert s["key"] == "mgmt"
    assert s["ssh_enabled"] is True
    for f in ("x_ssh_password", "x_ssh_md5passwd", "wifi_psk", "api_token", "secret_note", "admin_key"):
        assert s[f] == "***", f
    assert s["x_ssh_keys"] == "***"
    assert s["nested"] == {"radius_secret": "***", "visible": "ok"}
    dumped = json.dumps(result)
    for leaked in ("hash", "psk1", "tokval9", "ssh-rsa", "\"rs\""):
        assert leaked not in dumped


@respx.mock
async def test_settings_nonsecret_section_untouched_and_empty_secret_kept(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    respx.get(SETTING).mock(return_value=ok("site_insights_settings.json"))
    ntp = await get_site_settings(mock_client, section="ntp")
    assert ntp["settings"]["ntp_server_1"] == "ntp.example.com"
    radius = await get_site_settings(mock_client, section="radius")
    assert radius["settings"]["x_secret"] == ""


@respx.mock
async def test_settings_unknown_section(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    respx.get(SETTING).mock(return_value=ok("site_insights_settings.json"))
    result = await get_site_settings(mock_client, section="nope")
    assert result["category"] == "NOT_FOUND" and "ntp" in result["message"]


@pytest.mark.parametrize("section", ["", "  ", 5])
async def test_settings_validation(mock_client, section):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    assert (await get_site_settings(mock_client, section=section))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_settings_duplicate_sections_returned_as_list(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    data = {"data": [{"key": "x", "a": 1}, {"key": "x", "b": 2}]}
    respx.get(SETTING).mock(return_value=httpx.Response(200, json=data))
    result = await get_site_settings(mock_client, section="x")
    assert len(result["settings"]) == 2


@respx.mock
async def test_settings_shape_change(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    respx.get(SETTING).mock(return_value=httpx.Response(200, json={"weird": True}))
    result = await get_site_settings(mock_client)
    assert result["category"] == "UNEXPECTED_RESPONSE" and result["endpoint"].endswith("rest/setting")


def test_account_endpoint_not_exposed():
    from unifi_mcp.tools.network import routing, site_insights

    src = open(site_insights.__file__).read() + open(routing.__file__).read()
    assert "rest/account" not in src.replace("/rest/account endpoint", "")


@respx.mock
async def test_settings_masks_snmp_community_and_paypal_signature(mock_client):
    from unifi_mcp.tools.network.site_insights import get_site_settings

    respx.get(SETTING).mock(return_value=ok("site_insights_settings.json"))
    snmp = await get_site_settings(mock_client, section="snmp")
    assert snmp["settings"]["community"] == "***"
    assert snmp["settings"]["port"] == 161
    guest = await get_site_settings(mock_client, section="guest_access")
    assert guest["settings"]["paypal_signature"] == "***"
    assert guest["settings"]["portal_enabled"] is True


def test_neighbor_ssid_is_sanitized():
    from unifi_mcp.tools.network.site_insights import _clean_ssid

    assert _clean_ssid("Cafe\n\x00WiFi") == "CafeWiFi"
    assert len(_clean_ssid("x" * 500)) == 64


def test_vpn_config_blobs_are_masked():
    from unifi_mcp.tools.network.site_insights import mask_secrets

    masked = mask_secrets({"name": "v", "openvpn_configuration": "<key>abc</key>", "certificate": "pem"})
    assert masked["openvpn_configuration"] == "***" and masked["certificate"] == "***"
    assert masked["name"] == "v"
