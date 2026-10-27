"""Tests for create/update/delete ZBF policy tools on the official Integration API."""

import json

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig
from unifi_mcp.tools.network import zbf_policies_official as zp

SITE_UUID = "00000000-0000-0000-0000-000000000001"
BASE = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/firewall/policies"
IOT = "00000000-0000-0000-0000-0000000000a1"
SERVICES = "00000000-0000-0000-0000-0000000000a2"
INTERNAL = "00000000-0000-0000-0000-0000000000a3"
POLICY = "00000000-0000-0000-0000-0000000000c1"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    client = UnifiClient(config, TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def _current_policy(**overrides) -> dict:
    """A user-defined policy in the live 10.6.106 response shape."""
    policy = {
        "id": POLICY,
        "enabled": True,
        "name": "Observe IoT to Pi-hole DNS",
        "index": 10010,
        "action": {"type": "ALLOW", "allowReturnTraffic": False},
        "source": {"zoneId": IOT},
        "destination": {
            "zoneId": SERVICES,
            "trafficFilter": {
                "type": "IP_ADDRESS",
                "ipAddressFilter": {
                    "type": "IP_ADDRESSES", "matchOpposite": False,
                    "items": [{"type": "IP_ADDRESS", "value": "192.0.2.53"}],
                },
                "portFilter": {
                    "type": "PORTS", "matchOpposite": False,
                    "items": [{"type": "PORT_NUMBER", "value": 53}],
                },
            },
        },
        "ipProtocolScope": {
            "ipVersion": "IPV4_AND_IPV6",
            "protocolFilter": {"type": "PRESET", "preset": {"name": "TCP_UDP"}},
        },
        "loggingEnabled": True,
        "metadata": {"origin": "USER_DEFINED"},
    }
    return policy | overrides


# --- create ---

@respx.mock
@pytest.mark.asyncio
async def test_create_preview_returns_body_without_calling_api(mock_client):
    route = respx.post(BASE)
    result = await zp.create_zbf_policy_v1(
        mock_client, name="IoT DNS to Pi-hole", source_zone_id=IOT,
        destination_zone_id=SERVICES, destination_ips=["192.0.2.53"],
        destination_ports=[53], protocol="tcp_udp",
    )
    assert result["preview"] is True
    assert not route.called
    body = result["body"]
    assert body["name"] == "IoT DNS to Pi-hole"
    assert body["action"] == {"type": "ALLOW", "allowReturnTraffic": False}
    assert body["source"] == {"zoneId": IOT}
    assert body["destination"]["trafficFilter"]["type"] == "IP_ADDRESS"
    assert body["ipProtocolScope"]["protocolFilter"]["preset"] == {"name": "TCP_UDP"}
    assert body["loggingEnabled"] is False
    assert body["enabled"] is True
    assert "connectionStateFilter" not in body


@respx.mock
@pytest.mark.asyncio
async def test_create_confirmed_posts_exact_body(mock_client):
    created = {"id": POLICY, "name": "Block IoT to Internal"}
    route = respx.post(BASE).mock(return_value=httpx.Response(201, json=created))
    result = await zp.create_zbf_policy_v1(
        mock_client, name="Block IoT to Internal", source_zone_id=IOT,
        destination_zone_id=INTERNAL, action="BLOCK",
        connection_states=["NEW", "INVALID"], logging_enabled=True, confirm=True,
    )
    assert result["executed"] is True
    sent = json.loads(route.calls[0].request.content)
    assert sent == {
        "name": "Block IoT to Internal",
        "enabled": True,
        "action": {"type": "BLOCK"},
        "source": {"zoneId": IOT},
        "destination": {"zoneId": INTERNAL},
        "ipProtocolScope": {"ipVersion": "IPV4_AND_IPV6"},
        "connectionStateFilter": ["NEW", "INVALID"],
        "loggingEnabled": True,
    }


@respx.mock
@pytest.mark.asyncio
async def test_create_disabled_policy(mock_client):
    route = respx.post(BASE).mock(return_value=httpx.Response(201, json={"id": POLICY}))
    await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL,
        enabled=False, confirm=True,
    )
    assert json.loads(route.calls[0].request.content)["enabled"] is False


@respx.mock
@pytest.mark.asyncio
async def test_create_validation_error_makes_no_call(mock_client):
    route = respx.post(BASE)
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL,
        destination_ports=[53], protocol="all", confirm=True,
    )
    assert result["error"] is True
    assert not route.called


@pytest.mark.asyncio
async def test_create_rejects_address_family_mismatch(mock_client):
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL,
        destination_ips=["2001:db8::1"], ip_version="IPV4",
    )
    assert result["error"] is True


@pytest.mark.asyncio
async def test_create_preview_warns_on_zone_wide_allow(mock_client):
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL, action="ALLOW",
    )
    assert "all traffic" in result["warning"]


@pytest.mark.asyncio
async def test_create_preview_no_warning_when_filtered(mock_client):
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL,
        destination_ports=[631], protocol="tcp",
    )
    assert "warning" not in result


@pytest.mark.asyncio
async def test_create_rejects_return_flag_on_block(mock_client):
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL,
        action="BLOCK", allow_return_traffic=True,
    )
    assert result["error"] is True


@pytest.mark.asyncio
async def test_create_with_description(mock_client):
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL,
        action="BLOCK", description="segmentation P3",
    )
    assert result["body"]["description"] == "segmentation P3"


@pytest.mark.asyncio
async def test_create_rejects_blank_name(mock_client):
    result = await zp.create_zbf_policy_v1(
        mock_client, name="  ", source_zone_id=IOT, destination_zone_id=INTERNAL,
    )
    assert result["error"] is True


@respx.mock
@pytest.mark.asyncio
async def test_create_empty_response_is_not_reported_as_executed(mock_client):
    respx.post(BASE).mock(return_value=httpx.Response(200, content=b""))
    result = await zp.create_zbf_policy_v1(
        mock_client, name="t", source_zone_id=IOT, destination_zone_id=INTERNAL, confirm=True,
    )
    assert result["executed"] is False


# --- update ---

@respx.mock
@pytest.mark.asyncio
async def test_update_flip_allow_to_block_keeps_matchers(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    put = respx.put(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json={"id": POLICY}))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, action="BLOCK",
        connection_states=["NEW", "INVALID"], confirm=True,
    )
    assert result["executed"] is True
    sent = json.loads(put.calls[0].request.content)
    current = _current_policy()
    assert sent["action"] == {"type": "BLOCK"}
    assert sent["connectionStateFilter"] == ["NEW", "INVALID"]
    assert sent["destination"] == current["destination"]
    assert sent["source"] == current["source"]
    assert sent["ipProtocolScope"] == current["ipProtocolScope"]
    assert "id" not in sent and "metadata" not in sent and "index" not in sent


@respx.mock
@pytest.mark.asyncio
async def test_update_preview_shows_before_and_after(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    put = respx.put(f"{BASE}/{POLICY}")
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK")
    assert result["preview"] is True
    assert not put.called
    assert result["before"]["action"] == {"type": "ALLOW", "allowReturnTraffic": False}
    assert result["after"]["action"] == {"type": "BLOCK"}
    assert result["changed_fields"] == ["action"]


@respx.mock
@pytest.mark.asyncio
async def test_update_block_to_allow_sets_return_traffic(mock_client):
    current = _current_policy(action={"type": "BLOCK"})
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, action="ALLOW", allow_return_traffic=True,
    )
    assert result["after"]["action"] == {"type": "ALLOW", "allowReturnTraffic": True}


@respx.mock
@pytest.mark.asyncio
async def test_update_ports_only_keeps_ip_filter(mock_client):
    """Narrowing ports must not drop the existing IP filter (that would widen the rule)."""
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, destination_ports=[53, 853],
    )
    tf = result["after"]["destination"]["trafficFilter"]
    assert result["after"]["destination"]["zoneId"] == SERVICES
    assert tf["type"] == "IP_ADDRESS"
    assert tf["ipAddressFilter"] == _current_policy()["destination"]["trafficFilter"]["ipAddressFilter"]
    assert [i["value"] for i in tf["portFilter"]["items"]] == [53, 853]
    assert result["after"]["source"] == {"zoneId": IOT}
    assert result["changed_fields"] == ["destination"]


@respx.mock
@pytest.mark.asyncio
async def test_update_ips_only_keeps_port_filter(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, destination_ips=["192.0.2.54"],
    )
    tf = result["after"]["destination"]["trafficFilter"]
    assert tf["ipAddressFilter"]["items"] == [{"type": "IP_ADDRESS", "value": "192.0.2.54"}]
    assert tf["portFilter"] == _current_policy()["destination"]["trafficFilter"]["portFilter"]


@respx.mock
@pytest.mark.asyncio
async def test_update_zone_only_keeps_filters(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, destination_zone_id=INTERNAL,
    )
    dest = result["after"]["destination"]
    assert dest["zoneId"] == INTERNAL
    assert dest["trafficFilter"] == _current_policy()["destination"]["trafficFilter"]


@respx.mock
@pytest.mark.asyncio
async def test_update_clear_filters_is_explicit(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, clear_destination_filters=True,
        protocol="all",
    )
    assert result["after"]["destination"] == {"zoneId": SERVICES}


@respx.mock
@pytest.mark.asyncio
async def test_update_clear_then_set_ports(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, clear_destination_filters=True, destination_ports=[853],
    )
    tf = result["after"]["destination"]["trafficFilter"]
    assert tf["type"] == "PORT"
    assert "ipAddressFilter" not in tf


@respx.mock
@pytest.mark.asyncio
async def test_update_refuses_to_merge_unsupported_filter(mock_client):
    current = _current_policy(source={
        "zoneId": IOT,
        "trafficFilter": {"type": "MAC_ADDRESS", "macAddressFilter": {"macAddresses": ["aa:bb:cc:00:00:01"]}},
    })
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, source_ports=[1024], protocol="tcp")
    assert result["error"] is True
    assert "clear_source_filters" in result["message"]


@pytest.mark.parametrize("zone", ["", "not-a-uuid"])
@pytest.mark.asyncio
async def test_update_rejects_bad_zone_id_before_fetch(mock_client, zone):
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, source_zone_id=zone)
    assert result["error"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_confirm_refuses_if_policy_changed_since_preview(mock_client):
    route = respx.get(f"{BASE}/{POLICY}")
    put = respx.put(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json={"id": POLICY}))
    route.mock(return_value=httpx.Response(200, json=_current_policy()))
    preview = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK")
    assert preview["preview"] is True
    widened = _current_policy(destination={"zoneId": SERVICES})
    route.mock(return_value=httpx.Response(200, json=widened))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK", confirm=True)
    assert result["error"] is True
    assert result["category"] == "CONFLICT"
    assert not put.called


@respx.mock
@pytest.mark.asyncio
async def test_update_confirm_after_unchanged_preview_succeeds(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    put = respx.put(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json={"id": POLICY}))
    await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK")
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK", confirm=True)
    assert result["executed"] is True
    assert put.called


@respx.mock
@pytest.mark.asyncio
async def test_update_clear_connection_states(mock_client):
    current = _current_policy(connectionStateFilter=["NEW"])
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, clear_connection_states=True,
    )
    assert "connectionStateFilter" not in result["after"]


@respx.mock
@pytest.mark.asyncio
async def test_update_rejects_ports_with_all_protocols(mock_client):
    """The current policy matches port 53; switching to all protocols would be invalid."""
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, protocol="all")
    assert result["error"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_without_changes_is_an_error(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY)
    assert result["error"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_refuses_system_policy(mock_client):
    current = _current_policy(metadata={"origin": "SYSTEM_DEFINED"})
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK")
    assert result["error"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_not_found(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json={}))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK")
    assert result["category"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_update_rejects_v2_id_with_hint(mock_client):
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id="000000000000000000000001", action="BLOCK",
    )
    assert result["error"] is True
    assert "list_zbf_policies_v1" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_update_name_only_preserves_other_fields_and_drops_nulls(mock_client):
    current = _current_policy(
        description="observe window", schedule={"mode": "EVERY_DAY", "timeFilter": {"type": "ALL_DAY"}},
        ipsecFilter="MATCH_NOT_ENCRYPTED", connectionStateFilter=["NEW"],
    )
    current_with_null = current | {"description": None}
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, name="renamed")
    after = result["after"]
    for key in ("description", "schedule", "ipsecFilter", "connectionStateFilter", "source", "destination"):
        assert after[key] == current[key], key
    assert result["changed_fields"] == ["name"]

    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current_with_null))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, name="renamed")
    assert "description" not in result["after"]


@pytest.mark.parametrize("scope", [
    {"ipVersion": "IPV4", "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "tcp"}, "matchOpposite": False}},
    {"ipVersion": "IPV4", "protocolFilter": {"type": "PROTOCOL_NUMBER", "protocolNumber": 17, "matchOpposite": False}},
])
@respx.mock
@pytest.mark.asyncio
async def test_update_unrelated_field_does_not_recheck_protocol(mock_client, scope):
    respx.get(f"{BASE}/{POLICY}").mock(
        return_value=httpx.Response(200, json=_current_policy(ipProtocolScope=scope)))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, enabled=False)
    assert result["preview"] is True
    assert result["changed_fields"] == ["enabled"]


@respx.mock
@pytest.mark.asyncio
async def test_update_allow_to_block_drops_return_flag(mock_client):
    current = _current_policy(action={"type": "ALLOW", "allowReturnTraffic": True})
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, action="BLOCK")
    assert result["after"]["action"] == {"type": "BLOCK"}


@respx.mock
@pytest.mark.asyncio
async def test_update_protocol_only(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    result = await zp.update_zbf_policy_v1(mock_client, policy_id=POLICY, protocol="udp")
    assert result["after"]["ipProtocolScope"] == {
        "ipVersion": "IPV4_AND_IPV6",
        "protocolFilter": {"type": "NAMED_PROTOCOL", "protocol": {"name": "UDP"}, "matchOpposite": False},
    }


@respx.mock
@pytest.mark.asyncio
async def test_update_same_states_in_another_order_is_no_change(mock_client):
    """The console stores connection states in its own order (live: ["INVALID", "NEW"])."""
    current = _current_policy(connectionStateFilter=["INVALID", "NEW"])
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, connection_states=["NEW", "INVALID"],
    )
    assert result["error"] is True
    assert "No changes" in result["message"]


@respx.mock
@pytest.mark.asyncio
async def test_update_rejects_states_and_clear_together(mock_client):
    result = await zp.update_zbf_policy_v1(
        mock_client, policy_id=POLICY, connection_states=["NEW"], clear_connection_states=True,
    )
    assert result["error"] is True


# --- delete ---

@respx.mock
@pytest.mark.asyncio
async def test_delete_preview_names_policy(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    route = respx.delete(f"{BASE}/{POLICY}")
    result = await zp.delete_zbf_policy_v1(mock_client, policy_id=POLICY)
    assert result["preview"] is True
    assert result["name"] == "Observe IoT to Pi-hole DNS"
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_delete_confirmed(mock_client):
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=_current_policy()))
    route = respx.delete(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, content=b""))
    result = await zp.delete_zbf_policy_v1(mock_client, policy_id=POLICY, confirm=True)
    assert route.called
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_refuses_policy_without_origin(mock_client):
    current = {k: v for k, v in _current_policy().items() if k != "metadata"}
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    route = respx.delete(f"{BASE}/{POLICY}")
    result = await zp.delete_zbf_policy_v1(mock_client, policy_id=POLICY, confirm=True)
    assert result["error"] is True
    assert not route.called


@respx.mock
@pytest.mark.asyncio
async def test_delete_refuses_system_policy(mock_client):
    current = _current_policy(metadata={"origin": "SYSTEM_DEFINED"})
    respx.get(f"{BASE}/{POLICY}").mock(return_value=httpx.Response(200, json=current))
    route = respx.delete(f"{BASE}/{POLICY}")
    result = await zp.delete_zbf_policy_v1(mock_client, policy_id=POLICY, confirm=True)
    assert result["error"] is True
    assert not route.called


def test_module_registration():
    names = {t.__name__ for t in zp.TOOLS}
    assert names == {"create_zbf_policy_v1", "update_zbf_policy_v1", "delete_zbf_policy_v1"}
    assert set(zp.TIER2_TOOLS) == names
    assert zp.GROUP == "security"
