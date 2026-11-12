"""Official Network Integration API read tools added in v0.10.0 (all Tier 1).

Shapes follow the vendored spec 11.0.99 and were checked read-only against a
Network 11.0.99 console. WiFi passphrases must never appear in any output.
"""

import inspect
import json

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.network import acl_official, lookups, wifi_official
from unifi_mcp.validation import clean_text

SITE_UUID = "00000000-0000-0000-0000-000000000001"
HOST = "https://192.168.1.1"
ROOT = f"{HOST}/proxy/network/integration/v1"
SITE = f"{ROOT}/sites/{SITE_UUID}"
NET = "00000000-0000-0000-0000-0000000000b1"
NET2 = "00000000-0000-0000-0000-0000000000b2"
WIFI = "00000000-0000-0000-0000-0000000000d1"
RULE = "00000000-0000-0000-0000-0000000000e1"
SECRET = "correct-horse-battery-staple"
PPSK_SECRET = "ppsk-only-for-this-test"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", HOST)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    client = UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def page(rows):
    return httpx.Response(200, json={"data": rows, "offset": 0, "limit": 200, "count": len(rows), "totalCount": len(rows)})


# --- module contracts -----------------------------------------------------------


@pytest.mark.parametrize("module,group,names", [
    (wifi_official, "core", {"list_wifi_broadcasts_v1", "get_wifi_broadcast_v1"}),
    (acl_official, "security", {"list_acl_rules_v1", "get_acl_rule_v1"}),
])
def test_new_modules_are_read_only(module, group, names):
    assert module.GROUP == group and module.TIER2_TOOLS == {}
    assert {t.__name__ for t in module.TOOLS} == names
    for tool in module.TOOLS:
        assert "confirm" not in inspect.signature(tool).parameters and tool.__doc__


def test_lookups_gain_sites_and_network_detail():
    names = {t.__name__ for t in lookups.TOOLS}
    assert {"list_sites_v1", "get_network_v1"} <= names and len(lookups.TOOLS) == 16


def test_clean_text_strips_control_characters_and_caps():
    assert clean_text("Office\x1b[31m AP\n") == "Office[31m AP"
    assert clean_text(None) == "" and clean_text(5) == "5"
    assert clean_text("x" * 300, max_len=10) == "x" * 10


# --- sites and networks -------------------------------------------------------------


@respx.mock
async def test_list_sites_v1(mock_client):
    route = respx.get(f"{ROOT}/sites").mock(return_value=page([
        {"id": SITE_UUID, "internalReference": "default", "name": "Default\x07"},
    ]))
    assert await lookups.list_sites_v1(mock_client) == [
        {"id": SITE_UUID, "name": "Default", "internal_reference": "default"},
    ]
    assert route.calls[0].request.url.params["offset"] == "0"


@respx.mock
async def test_get_network_v1(mock_client):
    detail = {
        "management": "GATEWAY", "id": NET, "name": "IoT", "enabled": True, "vlanId": 30,
        "metadata": {"origin": "USER_DEFINED"}, "isolationEnabled": False,
        "cellularBackupEnabled": True, "zoneId": "00000000-0000-0000-0000-0000000000a1",
        "internetAccessEnabled": True, "mdnsForwardingEnabled": False, "default": False,
        "ipv4Configuration": {
            "autoScaleEnabled": False, "hostIpAddress": "192.0.2.1", "prefixLength": 24,
            "dhcpConfiguration": {"mode": "SERVER", "ipAddressRange": {"start": "192.0.2.10", "stop": "192.0.2.200"},
                                  "leaseTimeSeconds": 86400},
        },
        "unexpectedField": "dropped",
    }
    respx.get(f"{SITE}/networks/{NET}").mock(return_value=httpx.Response(200, json=detail))
    r = await lookups.get_network_v1(mock_client, NET)
    assert r["id"] == NET and r["vlan_id"] == 30 and r["management"] == "GATEWAY"
    assert r["origin"] == "USER_DEFINED" and r["zone_id"].endswith("a1")
    assert r["isolation_enabled"] is False and r["internet_access_enabled"] is True
    assert r["ipv4"]["prefixLength"] == 24 and "unexpectedField" not in r


async def test_get_network_v1_rejects_bad_id(mock_client):
    r = await lookups.get_network_v1(mock_client, "../sites")
    assert r["error"] is True


@respx.mock
async def test_get_network_v1_404_is_error_dict(mock_client):
    respx.get(f"{SITE}/networks/{NET}").mock(return_value=httpx.Response(404, json={"message": "nope"}))
    r = await lookups.get_network_v1(mock_client, NET)
    assert r["error"] is True and r["category"] == "NOT_FOUND"


# --- WiFi broadcasts -------------------------------------------------------------------


def _wifi_overview(**over):
    row = {
        "type": "STANDARD", "id": WIFI, "name": "Home\x1b", "enabled": True,
        "metadata": {"origin": "USER_DEFINED"},
        "network": {"type": "SPECIFIC", "networkId": NET},
        "securityConfiguration": {"type": "WPA2_PERSONAL", "presharedKeyNetworkIds": [
            {"type": "SPECIFIC", "networkId": NET}, {"type": "NATIVE"}]},
        "broadcastingFrequenciesGHz": [2.4, 5, 6],
        "hotspotConfiguration": {"type": "CAPTIVE_PORTAL"},
        "broadcastingDeviceFilter": {"type": "DEVICE_TAGS", "deviceTagIds": ["tag-1"]},
    }
    return row | over


def _wifi_detail():
    return {
        **{k: v for k, v in _wifi_overview().items() if k != "securityConfiguration"},
        "securityConfiguration": {
            "type": "WPA2_PERSONAL", "fastRoamingEnabled": True, "pmfMode": "OPTIONAL",
            "groupRekeyIntervalSeconds": 3600, "passphrase": SECRET,
            "presharedKeys": [
                {"network": {"type": "SPECIFIC", "networkId": NET}, "passphrase": PPSK_SECRET},
                {"network": {"type": "SPECIFIC", "networkId": NET2}, "passphrase": PPSK_SECRET},
            ],
            "radiusConfiguration": {"profileId": "rad-1", "nasId": {"type": "AUTO"}},
        },
        "clientIsolationEnabled": False, "hideName": False, "uapsdEnabled": True,
        "multicastToUnicastConversionEnabled": True, "arpProxyEnabled": True,
        "bssTransitionEnabled": True, "advertiseDeviceName": False,
        "channel2gLockedTo6": False, "dtimPeriod2gLockedTo3": False,
        "clientFilteringPolicy": {"action": "BLOCK", "macAddressFilter": "aa:bb:cc:00:00:99"},
        "mdnsProxyConfiguration": {"mode": "AUTO"},
        "multicastFilteringPolicy": {"action": "ALLOW"},
        "blackoutScheduleConfiguration": {"days": [{"day": "MON", "type": "ALL_DAY"}]},
    }


@respx.mock
async def test_list_wifi_broadcasts_v1(mock_client):
    respx.get(f"{SITE}/wifi/broadcasts").mock(return_value=page([_wifi_overview(), "junk"]))
    rows = await wifi_official.list_wifi_broadcasts_v1(mock_client)
    assert rows == [{
        "id": WIFI, "name": "Home", "type": "STANDARD", "enabled": True, "origin": "USER_DEFINED",
        "network": {"type": "SPECIFIC", "network_id": NET},
        "security_type": "WPA2_PERSONAL",
        "ppsk_networks": [{"type": "SPECIFIC", "network_id": NET}, {"type": "NATIVE", "network_id": None}],
        "frequencies_ghz": [2.4, 5, 6], "hotspot_type": "CAPTIVE_PORTAL",
        "broadcasting_devices": {"type": "DEVICE_TAGS", "device_ids": [], "device_tag_ids": ["tag-1"]},
    }]


@respx.mock
async def test_get_wifi_broadcast_v1_never_returns_secrets(mock_client):
    respx.get(f"{SITE}/wifi/broadcasts/{WIFI}").mock(return_value=httpx.Response(200, json=_wifi_detail()))
    r = await wifi_official.get_wifi_broadcast_v1(mock_client, WIFI)
    text = json.dumps(r)
    assert SECRET not in text and PPSK_SECRET not in text and '"passphrase"' not in text
    sec = r["security"]
    assert sec["type"] == "WPA2_PERSONAL" and sec["has_passphrase"] is True
    assert sec["ppsk_count"] == 2 and sec["ppsk_network_ids"] == [NET, NET2]
    assert sec["pmf_mode"] == "OPTIONAL" and sec["fast_roaming_enabled"] is True
    assert sec["radius_profile_id"] == "rad-1"
    assert r["client_isolation_enabled"] is False and r["hide_name"] is False
    assert r["client_filtering_action"] == "BLOCK" and "aa:bb:cc:00:00:99" not in text
    assert r["mdns_proxy_mode"] == "AUTO" and r["blackout_schedule_days"] == 1


@respx.mock
async def test_get_wifi_broadcast_v1_open_network(mock_client):
    detail = {"type": "IOT_OPTIMIZED", "id": WIFI, "name": "Things", "enabled": False,
              "securityConfiguration": {"type": "OPEN", "encryption": "ENHANCED_OPEN"}}
    respx.get(f"{SITE}/wifi/broadcasts/{WIFI}").mock(return_value=httpx.Response(200, json=detail))
    r = await wifi_official.get_wifi_broadcast_v1(mock_client, WIFI)
    assert r["security"]["has_passphrase"] is False and r["security"]["ppsk_count"] == 0
    assert r["security"]["encryption"] == "ENHANCED_OPEN" and r["type"] == "IOT_OPTIMIZED"


async def test_get_wifi_broadcast_v1_validation(mock_client):
    assert (await wifi_official.get_wifi_broadcast_v1(mock_client, ""))["error"] is True


@respx.mock
async def test_list_wifi_broadcasts_v1_error_is_dict(mock_client):
    respx.get(f"{SITE}/wifi/broadcasts").mock(return_value=httpx.Response(403))
    r = await wifi_official.list_wifi_broadcasts_v1(mock_client)
    assert r["error"] is True


# --- ACL rules -------------------------------------------------------------------------


def _ip_rule():
    return {
        "type": "IPV4", "id": RULE, "name": "Block cams to LAN", "enabled": True, "action": "BLOCK",
        "index": 3, "description": "d", "metadata": {"origin": "USER_DEFINED"},
        "enforcingDeviceFilter": {"type": "DEVICES", "deviceIds": ["dev-1"]},
        "sourceFilter": {"type": "IP_ADDRESSES_OR_SUBNETS", "ipAddressesOrSubnets": ["192.0.2.0/24"], "portFilter": [554]},
        "destinationFilter": {"type": "NETWORKS", "networkIds": [NET], "portFilter": []},
        "protocolFilter": ["TCP"],
    }


def _mac_rule():
    return {
        "type": "MAC", "id": RULE, "name": "Allow printer", "enabled": False, "action": "ALLOW", "index": 1,
        "metadata": {"origin": "USER_DEFINED"}, "networkIdFilter": NET,
        "sourceFilter": {"type": "MAC_ADDRESSES", "macAddresses": ["aa:bb:cc:00:00:01"], "prefixLength": 48},
    }


@respx.mock
async def test_list_acl_rules_v1(mock_client):
    respx.get(f"{SITE}/acl-rules").mock(return_value=page([_ip_rule(), _mac_rule()]))
    rows = await acl_official.list_acl_rules_v1(mock_client)
    assert rows[0] == {
        "id": RULE, "name": "Block cams to LAN", "type": "IPV4", "enabled": True, "action": "BLOCK",
        "index": 3, "description": "d", "origin": "USER_DEFINED",
        "enforcing_device_ids": ["dev-1"], "protocols": ["TCP"], "network_id": None,
        "source": {"type": "IP_ADDRESSES_OR_SUBNETS", "ip_addresses_or_subnets": ["192.0.2.0/24"],
                   "network_ids": [], "mac_addresses": [], "ports": [554], "prefix_length": None},
        "destination": {"type": "NETWORKS", "ip_addresses_or_subnets": [], "network_ids": [NET],
                        "mac_addresses": [], "ports": [], "prefix_length": None},
    }
    assert rows[1]["type"] == "MAC" and rows[1]["network_id"] == NET
    assert rows[1]["source"]["mac_addresses"] == ["aa:bb:cc:00:00:01"] and rows[1]["destination"] is None


@respx.mock
async def test_list_acl_rules_v1_empty(mock_client):
    respx.get(f"{SITE}/acl-rules").mock(return_value=page([]))
    assert await acl_official.list_acl_rules_v1(mock_client) == []


@respx.mock
async def test_get_acl_rule_v1(mock_client):
    respx.get(f"{SITE}/acl-rules/{RULE}").mock(return_value=httpx.Response(200, json=_mac_rule()))
    r = await acl_official.get_acl_rule_v1(mock_client, RULE)
    assert r["id"] == RULE and r["action"] == "ALLOW" and r["enabled"] is False


async def test_get_acl_rule_v1_validation(mock_client):
    assert (await acl_official.get_acl_rule_v1(mock_client, "a/b"))["error"] is True


@respx.mock
async def test_get_acl_rule_v1_not_found(mock_client):
    respx.get(f"{SITE}/acl-rules/{RULE}").mock(return_value=httpx.Response(404))
    r = await acl_official.get_acl_rule_v1(mock_client, RULE)
    assert r["error"] is True and r["category"] == "NOT_FOUND"


@respx.mock
async def test_get_network_v1_cleans_free_text_in_config(mock_client):
    detail = {"id": NET, "name": "LAN", "ipv4Configuration": {"dhcpConfiguration": {
        "domainName": "home\x1b[2J.example", "option43Value": "x" * 400, "leaseTimeSeconds": 60,
        "dnsServerIpAddressesOverride": ["192.0.2.53"]}}}
    respx.get(f"{SITE}/networks/{NET}").mock(return_value=httpx.Response(200, json=detail))
    dhcp = (await lookups.get_network_v1(mock_client, NET))["ipv4"]["dhcpConfiguration"]
    assert dhcp["domainName"] == "home[2J.example" and len(dhcp["option43Value"]) == 256
    assert dhcp["leaseTimeSeconds"] == 60 and dhcp["dnsServerIpAddressesOverride"] == ["192.0.2.53"]
