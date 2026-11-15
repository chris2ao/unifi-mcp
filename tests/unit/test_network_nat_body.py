"""Unit tests for NAT rule body validation and building (no HTTP)."""
import pytest

from unifi_mcp.tools.network.nat_body import build_filter, build_rule, is_error

DEFAULT_ID = "00000000-0000-0000-0000-0000000000d1"


def rule(**overrides):
    """build_rule with a valid DNAT NTP redirect as the base."""
    args = {
        "description": "NTP redirect to resolver-a",
        "nat_type": "DNAT",
        "protocol": "udp",
        "ip_version": "IPV4",
        "in_interface": DEFAULT_ID,
        "out_interface": None,
        "translated_ip": "192.0.2.53",
        "translated_port": "123",
        "source": None,
        "destination": {"port": "123"},
        "exclude": False,
        "enabled": True,
        "logging": False,
        "rule_index": 2,
    }
    args.update(overrides)
    return build_rule(**args)


def assert_error(result, *fragments):
    assert is_error(result), result
    for fragment in fragments:
        assert fragment in result["message"], result["message"]


# --- valid bodies -----------------------------------------------------------

def test_dnat_ntp_redirect_body():
    assert rule() == {
        "description": "NTP redirect to resolver-a",
        "type": "DNAT",
        "protocol": "udp",
        "ip_version": "IPV4",
        "enabled": True,
        "exclude": False,
        "logging": False,
        "rule_index": 2,
        "in_interface": DEFAULT_ID,
        "ip_address": "192.0.2.53",
        "port": "123",
        "source_filter": {"filter_type": "NONE"},
        "destination_filter": {
            "filter_type": "ADDRESS_AND_PORT", "port": "123",
            "invert_address": False, "invert_port": False,
        },
    }


def test_exclude_rule_has_no_translation():
    body = rule(exclude=True, translated_ip=None, translated_port=None,
                source={"address": "192.0.2.53"})
    assert body["exclude"] is True
    assert "ip_address" not in body and "port" not in body
    assert body["source_filter"] == {
        "filter_type": "ADDRESS_AND_PORT", "address": "192.0.2.53",
        "invert_address": False, "invert_port": False,
    }


def test_masquerade_body_uses_out_interface():
    body = rule(nat_type="MASQUERADE", in_interface=None, out_interface=DEFAULT_ID,
                translated_ip=None, translated_port=None,
                source={"address": "192.0.2.0/24"},
                destination={"address": "192.0.2.53", "port": "123"})
    assert body["out_interface"] == DEFAULT_ID
    assert "in_interface" not in body and "ip_address" not in body and "port" not in body
    assert body["source_filter"]["address"] == "192.0.2.0/24"
    assert body["destination_filter"]["address"] == "192.0.2.53"


def test_snat_with_translated_ip():
    body = rule(nat_type="SNAT", in_interface=None, out_interface=DEFAULT_ID, translated_port=None)
    assert body["type"] == "SNAT" and body["ip_address"] == "192.0.2.53"


def test_rule_index_omitted_when_none():
    assert "rule_index" not in rule(rule_index=None)


def test_int_ports_become_strings():
    body = rule(translated_port=123, destination={"port": 123})
    assert body["port"] == "123" and body["destination_filter"]["port"] == "123"


def test_ipv6_rule():
    body = rule(ip_version="IPV6", translated_ip="fd00::53", destination={"address": "fd00::/64"})
    assert body["ip_address"] == "fd00::53"


def test_filter_network_and_groups():
    assert build_filter("source", {"network_id": DEFAULT_ID}, "IPV4") == {
        "filter_type": "NETWORK_CONF", "network_conf_id": DEFAULT_ID,
    }
    assert build_filter("source", {"firewall_group_ids": ["abc123"]}, "IPV4") == {
        "filter_type": "FIREWALL_GROUPS", "firewall_group_ids": ["abc123"],
    }
    assert build_filter("source", {}, "IPV4") == {"filter_type": "NONE"}


def test_filter_invert_flags_carried():
    f = build_filter("source", {"address": "192.0.2.53", "invert_address": True}, "IPV4")
    assert f["invert_address"] is True and f["invert_port"] is False


# --- errors -----------------------------------------------------------------

def test_dnat_requires_in_interface():
    assert_error(rule(in_interface=None), "in_interface")


def test_dnat_rejects_out_interface():
    assert_error(rule(out_interface=DEFAULT_ID), "out_interface")


@pytest.mark.parametrize("nat_type", ["SNAT", "MASQUERADE"])
def test_snat_and_masquerade_require_out_interface(nat_type):
    assert_error(rule(nat_type=nat_type, translated_port=None), "out_interface")


def test_masquerade_rejects_in_interface():
    assert_error(rule(nat_type="MASQUERADE", out_interface=DEFAULT_ID, translated_ip=None,
                      translated_port=None), "in_interface")


def test_masquerade_rejects_translated_ip():
    assert_error(rule(nat_type="MASQUERADE", in_interface=None, out_interface=DEFAULT_ID,
                      translated_port=None), "translated_ip")


def test_masquerade_rejects_translated_port():
    assert_error(rule(nat_type="MASQUERADE", in_interface=None, out_interface=DEFAULT_ID,
                      translated_ip=None), "translated_port")


def test_dnat_requires_translated_ip_unless_exclude():
    assert_error(rule(translated_ip=None), "translated_ip")


def test_snat_requires_translated_ip_unless_exclude():
    assert_error(rule(nat_type="SNAT", in_interface=None, out_interface=DEFAULT_ID,
                      translated_ip=None, translated_port=None), "translated_ip")


def test_exclude_rejects_translated_ip_and_port():
    assert_error(rule(exclude=True, translated_port=None), "exclude", "translated_ip")
    assert_error(rule(exclude=True, translated_ip=None), "exclude", "translated_port")


def test_translated_ip_must_be_single_address():
    assert_error(rule(translated_ip="192.0.2.0/24"), "translated_ip")
    assert_error(rule(translated_ip="not-an-ip"), "translated_ip")


@pytest.mark.parametrize("overrides", [
    {"translated_port": "123", "destination": None},
    {"translated_port": None, "destination": {"port": "123"}},
    {"translated_port": None, "destination": None, "source": {"port": "5000"}},
])
def test_port_requires_protocol_other_than_all(overrides):
    assert_error(rule(protocol="all", **overrides), "protocol")


def test_translated_port_rejects_range():
    assert_error(rule(translated_port="8080-8090"), "translated_port")


@pytest.mark.parametrize("port", ["8080-8090", "1", "65535", 443])
def test_filter_port_accepts_single_and_range(port):
    assert not is_error(build_filter("destination", {"port": port}, "IPV4"))


@pytest.mark.parametrize("port", ["9000-8000", "0", "65536", "80,443", " 80", "abc", "", True, 1.5])
def test_filter_port_rejects_bad_values(port):
    assert_error(build_filter("destination", {"port": port}, "IPV4"), "port")


@pytest.mark.parametrize("port", ["0", "65536", "abc", True])
def test_translated_port_rejects_bad_values(port):
    assert_error(rule(translated_port=port), "translated_port")


def test_cidr_with_host_bits_rejected():
    assert_error(build_filter("source", {"address": "192.0.2.5/24"}, "IPV4"),
                 "192.0.2.0/24")


def test_address_family_must_match_ip_version():
    assert_error(build_filter("source", {"address": "fd00::1"}, "IPV4"), "IPV4")
    assert_error(rule(translated_ip="fd00::1"), "translated_ip", "IPV4")


def test_bad_address_rejected():
    assert_error(build_filter("source", {"address": "192.0.2.999"}, "IPV4"), "address")
    assert_error(build_filter("source", {"address": 17}, "IPV4"), "address")


def test_filter_families_are_exclusive():
    assert_error(build_filter("source", {"address": "192.0.2.1", "network_id": DEFAULT_ID}, "IPV4"),
                 "source")
    assert_error(build_filter("source", {"network_id": DEFAULT_ID, "firewall_group_ids": ["a"]}, "IPV4"),
                 "source")


def test_unknown_filter_key_rejected():
    assert_error(build_filter("source", {"adress": "192.0.2.1"}, "IPV4"), "adress")


def test_filter_must_be_dict():
    assert_error(build_filter("source", "192.0.2.1", "IPV4"), "source")


def test_invert_without_value_rejected():
    assert_error(build_filter("source", {"port": "123", "invert_address": True}, "IPV4"), "invert_address")
    assert_error(build_filter("source", {"address": "192.0.2.1", "invert_port": True}, "IPV4"), "invert_port")


def test_invert_must_be_bool():
    assert_error(build_filter("source", {"address": "192.0.2.1", "invert_address": "yes"}, "IPV4"),
                 "invert_address")


def test_bad_ids_rejected():
    assert_error(build_filter("source", {"network_id": "../x"}, "IPV4"), "network_id")
    assert_error(build_filter("source", {"firewall_group_ids": []}, "IPV4"), "firewall_group_ids")
    assert_error(build_filter("source", {"firewall_group_ids": ["ok", "bad/id"]}, "IPV4"),
                 "firewall_group_ids")
    assert_error(rule(in_interface="bad id"), "in_interface")


@pytest.mark.parametrize("description", ["", "   ", "line\nbreak", None, "x" * 129])
def test_description_rejects_empty_control_chars_and_long(description):
    assert_error(rule(description=description), "description")


@pytest.mark.parametrize("rule_index", [-1, True, "2", 1.0])
def test_rule_index_must_be_non_negative_int(rule_index):
    assert_error(rule(rule_index=rule_index), "rule_index")


@pytest.mark.parametrize("field,value", [
    ("nat_type", "PAT"), ("protocol", "icmp"), ("ip_version", "4"),
])
def test_enum_fields_validated(field, value):
    assert_error(rule(**{field: value}), field)


@pytest.mark.parametrize("field", ["exclude", "enabled", "logging"])
def test_bool_fields_validated(field):
    assert_error(rule(**{field: "true"}), field)


def test_is_error():
    assert is_error({"error": True, "message": "x"})
    assert not is_error({"error": False})
    assert not is_error({"filter_type": "NONE"})
    assert not is_error(None)
