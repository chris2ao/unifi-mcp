"""Tests for the official-API firewall policy body builder (zbf_policy_filters).

Shapes mirror policies read live from Network 10.6.106 on 2026-10-26.
"""

import pytest

from unifi_mcp.tools.network import zbf_policy_filters as f

ZONE = "00000000-0000-0000-0000-00000000000a"
NET = "00000000-0000-0000-0000-0000000000b1"


def _err(result) -> bool:
    return isinstance(result, dict) and result.get("error") is True


# --- IP items ---

@pytest.mark.parametrize("value, expected", [
    ("192.0.2.10", {"type": "IP_ADDRESS", "value": "192.0.2.10"}),
    ("192.0.2.0/24", {"type": "SUBNET", "value": "192.0.2.0/24"}),
    ("192.0.2.10-192.0.2.20", {"type": "IP_ADDRESS_RANGE", "start": "192.0.2.10", "stop": "192.0.2.20"}),
    (" 192.0.2.10 ", {"type": "IP_ADDRESS", "value": "192.0.2.10"}),
])
def test_ip_item_shapes(value, expected):
    assert f.ip_item(value) == expected


@pytest.mark.parametrize("value", [
    "192.0.2.300", "192.0.2.1/33", "192.0.2.20-192.0.2.10", "not-an-ip", "", 42, None,
    "192.0.2.5/24",  # host bits set: ambiguous, reject rather than guess
])
def test_ip_item_rejects_bad_values(value):
    assert _err(f.ip_item(value))


# --- port items ---

@pytest.mark.parametrize("value, expected", [
    (53, {"type": "PORT_NUMBER", "value": 53}),
    ("443", {"type": "PORT_NUMBER", "value": 443}),
    ("8000-8100", {"type": "PORT_NUMBER_RANGE", "start": 8000, "stop": 8100}),
])
def test_port_item_shapes(value, expected):
    assert f.port_item(value) == expected


@pytest.mark.parametrize("value", [0, 65536, "abc", "9-3", "1-70000", True, None, 5.5, "\u00b2", "1-\u00b2", "\u0665\u0663"])
def test_port_item_rejects_bad_values(value):
    assert _err(f.port_item(value))


# --- endpoints (source / destination) ---

def test_endpoint_zone_only():
    assert f.build_endpoint(ZONE, side="source") == {"zoneId": ZONE}


def test_endpoint_ips_with_ports():
    out = f.build_endpoint(ZONE, ips=["192.0.2.10"], ports=[53], side="destination")
    assert out == {
        "zoneId": ZONE,
        "trafficFilter": {
            "type": "IP_ADDRESS",
            "ipAddressFilter": {
                "type": "IP_ADDRESSES", "matchOpposite": False,
                "items": [{"type": "IP_ADDRESS", "value": "192.0.2.10"}],
            },
            "portFilter": {
                "type": "PORTS", "matchOpposite": False,
                "items": [{"type": "PORT_NUMBER", "value": 53}],
            },
        },
    }


def test_endpoint_networks_without_ports():
    out = f.build_endpoint(ZONE, network_ids=[NET], side="source")
    assert out["trafficFilter"] == {
        "type": "NETWORK",
        "networkFilter": {"networkIds": [NET], "matchOpposite": False},
    }


def test_endpoint_ports_only():
    out = f.build_endpoint(ZONE, ports=["8096", 8920], side="destination")
    assert out["trafficFilter"] == {
        "type": "PORT",
        "portFilter": {
            "type": "PORTS", "matchOpposite": False,
            "items": [{"type": "PORT_NUMBER", "value": 8096}, {"type": "PORT_NUMBER", "value": 8920}],
        },
    }


@pytest.mark.parametrize("kwargs", [
    {"ips": ["192.0.2.1"], "network_ids": [NET]},   # pick one matcher
    {"ips": []},                                    # empty list is a mistake, not "any"
    {"ports": []},
    {"ips": "192.0.2.1"},                           # must be a list
    {"network_ids": ["not-a-uuid"]},
    {"ips": ["192.0.2.1", "bad"]},
    {"ports": [53, 70000]},
])
def test_endpoint_rejects_bad_matchers(kwargs):
    assert _err(f.build_endpoint(ZONE, side="source", **kwargs))


def test_endpoint_rejects_bad_zone():
    assert _err(f.build_endpoint("000000000000000000000001", side="source"))


# --- protocol scope ---

def test_scope_all_protocols():
    assert f.build_ip_scope("all", "IPV4_AND_IPV6", has_ports=False) == {"ipVersion": "IPV4_AND_IPV6"}


def test_scope_tcp_udp_preset():
    assert f.build_ip_scope("tcp_udp", "IPV4_AND_IPV6", has_ports=True) == {
        "ipVersion": "IPV4_AND_IPV6",
        "protocolFilter": {"type": "PRESET", "preset": {"name": "TCP_UDP"}},
    }


def test_scope_named_protocol():
    assert f.build_ip_scope("tcp", "IPV4", has_ports=True) == {
        "ipVersion": "IPV4",
        "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "TCP"}, "matchOpposite": False},
    }


@pytest.mark.parametrize("protocol, version, has_ports", [
    ("all", "IPV4", True),          # ports need tcp, udp or tcp_udp
    ("icmp", "IPV4", True),
    ("icmp", "IPV4_AND_IPV6", False),  # ICMP is IPv4 only
    ("sctp", "IPV4", False),
    ("tcp", "IPV5", False),
])
def test_scope_rejects_bad_combinations(protocol, version, has_ports):
    assert _err(f.build_ip_scope(protocol, version, has_ports=has_ports))


# --- action and connection states ---

def test_action_allow_carries_return_traffic():
    assert f.build_action("ALLOW", allow_return_traffic=True) == {"type": "ALLOW", "allowReturnTraffic": True}


def test_action_block_has_no_return_flag():
    assert f.build_action("block", allow_return_traffic=False) == {"type": "BLOCK"}


def test_action_rejects_unknown():
    assert _err(f.build_action("DROP", allow_return_traffic=False))


def test_connection_states_normalized():
    assert f.check_connection_states(["new", "INVALID"]) == ["NEW", "INVALID"]


@pytest.mark.parametrize("value", [[], ["NEW", "BOGUS"], "NEW", ["NEW", "NEW"]])
def test_connection_states_rejects_bad(value):
    assert _err(f.check_connection_states(value))


# --- address family vs ip_version ---

def test_ip_family_matches_version():
    ep = f.build_endpoint(ZONE, ips=["192.0.2.1", "198.51.100.0/24"], side="destination")
    assert f.check_ip_family(ep, "IPV4") is None
    assert f.check_ip_family(ep, "IPV4_AND_IPV6") is None
    assert _err(f.check_ip_family(ep, "IPV6"))


def test_ip_family_rejects_v6_on_v4_rule():
    ep = f.build_endpoint(ZONE, ips=["2001:db8::1"], side="destination")
    assert _err(f.check_ip_family(ep, "IPV4"))


def test_ip_family_ignores_sides_without_ips():
    assert f.check_ip_family({"zoneId": ZONE}, "IPV4") is None


# --- scope_allows_ports (existing scopes read from the console) ---

@pytest.mark.parametrize("scope, expected", [
    ({"ipVersion": "IPV4_AND_IPV6", "protocolFilter": {"type": "PRESET", "preset": {"name": "TCP_UDP"}}}, True),
    # Live 10.6.106 GETs return upper-case names ({"name": "TCP"}); accept either case.
    ({"ipVersion": "IPV4", "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "TCP"}, "matchOpposite": False}}, True),
    ({"ipVersion": "IPV4", "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "udp"}, "matchOpposite": False}}, True),
    ({"ipVersion": "IPV4", "protocolFilter": {"type": "PROTOCOL_NUMBER", "protocolNumber": 6, "matchOpposite": False}}, True),
    ({"ipVersion": "IPV4", "protocolFilter": {"type": "PROTOCOL_NUMBER", "protocolNumber": 47, "matchOpposite": False}}, False),
    ({"ipVersion": "IPV4", "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "ICMP"}, "matchOpposite": False}}, False),
    ({"ipVersion": "IPV4", "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "TCP"}, "matchOpposite": True}}, False),
    ({"ipVersion": "IPV4_AND_IPV6"}, False),
])
def test_scope_allows_ports(scope, expected):
    assert f.scope_allows_ports(scope) is expected


# --- duplicates and return-traffic flag ---

@pytest.mark.parametrize("kwargs", [
    {"ips": ["192.0.2.1", "192.0.2.1"]},
    {"ports": [53, "53"]},
    {"network_ids": [NET, NET]},
])
def test_endpoint_rejects_duplicates(kwargs):
    assert _err(f.build_endpoint(ZONE, side="source", **kwargs))


def test_action_rejects_return_flag_on_block():
    assert _err(f.build_action("BLOCK", allow_return_traffic=True))
