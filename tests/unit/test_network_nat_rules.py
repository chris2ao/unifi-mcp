"""respx tests for the NAT rule write tools (v2 /nat endpoint)."""
import copy
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
NAT = f"{BASE}/v2/api/site/default/nat"
NETWORKS = f"{BASE}/api/s/default/rest/networkconf"
GROUPS = f"{BASE}/api/s/default/rest/firewallgroup"

DEFAULT_ID = "net001"
WAN_ID = "00000000-0000-0000-0000-00000000wan1"
NETWORK_PAYLOAD = {"meta": {"rc": "ok"}, "data": [
    {"_id": DEFAULT_ID, "name": "Default"},
    {"_id": WAN_ID, "name": "Internet 1"},
    {"_id": "00000000-0000-0000-0000-00000000lan1", "name": "LAN"},
    {"_id": "00000000-0000-0000-0000-00000000lab1", "name": "Lab"},
]}
DNAT_ID = "6735a1f04ee8cb0f1f4a0001"
MASQ_ID = "6735a1f04ee8cb0f1f4a0002"
PREDEFINED_ID = "6735a1f04ee8cb0f1f4a0003"
NEW_ID = "6735a1f04ee8cb0f1f4a0099"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.0.2.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


@pytest.fixture(autouse=True)
def clear_previews():
    from unifi_mcp.tools.network import nat_rules

    nat_rules._previewed.clear()
    yield
    nat_rules._previewed.clear()


def rules():
    return copy.deepcopy(load_fixture("nat_rules.json"))


def mock_lookups():
    respx.get(NETWORKS).mock(return_value=httpx.Response(200, json=NETWORK_PAYLOAD))
    respx.get(GROUPS).mock(return_value=httpx.Response(200, json=load_fixture("firewall_groups.json")))


def ntp_args(**overrides):
    args = {
        "description": "NTP redirect to resolver-a", "nat_type": "DNAT", "protocol": "udp",
        "in_interface": DEFAULT_ID, "translated_ip": "192.0.2.53", "translated_port": 123,
        "destination": {"port": "123"},
    }
    args.update(overrides)
    return args


def saved(body: dict, rule_id: str = NEW_ID) -> dict:
    return {"_id": rule_id, "is_predefined": False, "setting_preference": "manual", **body}


# --- module ------------------------------------------------------------------

def test_module_conventions():
    from unifi_mcp.tools.network import nat_rules

    assert nat_rules.GROUP == "security"
    assert nat_rules.TIER2_TOOLS == {"create_nat_rule": "routing"}
    assert [t.__name__ for t in nat_rules.TOOLS] == ["get_nat_rule", "create_nat_rule"]


# --- get ---------------------------------------------------------------------

@respx.mock
async def test_get_nat_rule_found(mock_client):
    from unifi_mcp.tools.network.nat_rules import get_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    result = await get_nat_rule(mock_client, DNAT_ID)
    assert result["id"] == DNAT_ID and result["type"] == "DNAT" and result["rule_index"] == 1


@respx.mock
async def test_get_nat_rule_not_found(mock_client):
    from unifi_mcp.tools.network.nat_rules import get_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    result = await get_nat_rule(mock_client, "missing")
    assert result["category"] == "NOT_FOUND" and result["rule_id"] == "missing"


async def test_get_nat_rule_rejects_bad_id(mock_client):
    from unifi_mcp.tools.network.nat_rules import get_nat_rule

    assert (await get_nat_rule(mock_client, "../x"))["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_get_nat_rule_is_not_cached(mock_client):
    from unifi_mcp.tools.network.nat_rules import get_nat_rule

    route = respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    await get_nat_rule(mock_client, DNAT_ID)
    await get_nat_rule(mock_client, DNAT_ID)
    assert route.call_count == 2


# --- create ------------------------------------------------------------------

@respx.mock
async def test_create_preview_sends_nothing(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    post = respx.post(NAT)
    result = await create_nat_rule(mock_client, **ntp_args())
    assert result["preview"] is True and result["action"] == "create_nat_rule"
    assert result["body"]["ip_address"] == "192.0.2.53" and result["body"]["rule_index"] == 3
    assert "impact" in result
    assert not post.called


async def test_create_validation_error_needs_no_network(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    result = await create_nat_rule(mock_client, **ntp_args(protocol="all"))
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_create_rejects_unknown_interface(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    result = await create_nat_rule(mock_client, **ntp_args(in_interface="net999"))
    assert result["category"] == "VALIDATION_ERROR" and "net999" in result["message"]


@respx.mock
async def test_create_rejects_unknown_filter_network_and_group(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    result = await create_nat_rule(mock_client, **ntp_args(source={"network_id": "net404"}))
    assert result["category"] == "VALIDATION_ERROR" and "net404" in result["message"]
    result = await create_nat_rule(mock_client, **ntp_args(source={"firewall_group_ids": ["fwg001", "fwg404"]}))
    assert result["category"] == "VALIDATION_ERROR" and "fwg404" in result["message"]


@respx.mock
async def test_create_accepts_known_group(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    result = await create_nat_rule(mock_client, **ntp_args(source={"firewall_group_ids": ["fwg001"]}))
    assert result["preview"] is True


@respx.mock
async def test_create_assigns_next_rule_index(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    body_holder = {}

    def on_post(request):
        body_holder["body"] = json.loads(request.content)
        return httpx.Response(200, json=saved(body_holder["body"]))

    respx.get(NAT).mock(side_effect=lambda r: httpx.Response(
        200, json=rules() + ([saved(body_holder["body"])] if "body" in body_holder else [])))
    mock_lookups()
    respx.post(NAT).mock(side_effect=on_post)
    result = await create_nat_rule(mock_client, **ntp_args(), confirm=True)
    assert body_holder["body"]["rule_index"] == 3
    assert result["executed"] is True and result["verified"] is True


@respx.mock
async def test_create_first_rule_gets_index_zero(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=[]))
    mock_lookups()
    result = await create_nat_rule(mock_client, **ntp_args())
    assert result["body"]["rule_index"] == 0


@respx.mock
async def test_create_rejects_taken_rule_index(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    result = await create_nat_rule(mock_client, **ntp_args(rule_index=2))
    assert result["category"] == "VALIDATION_ERROR" and "rule_index" in result["message"]


@respx.mock
async def test_create_confirm_posts_and_verifies(mock_client, monkeypatch):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    invalidated = []
    monkeypatch.setattr(mock_client, "invalidate_cache", invalidated.append)
    posted = {}

    def on_post(request):
        posted["body"] = json.loads(request.content)
        return httpx.Response(200, json=saved(posted["body"]))

    respx.get(NAT).mock(side_effect=lambda r: httpx.Response(
        200, json=rules() + ([saved(posted["body"])] if posted else [])))
    mock_lookups()
    respx.post(NAT).mock(side_effect=on_post)
    result = await create_nat_rule(mock_client, **ntp_args(), confirm=True)
    assert result["executed"] is True and result["verified"] is True
    assert result["rule"]["id"] == NEW_ID and "mismatches" not in result
    assert invalidated == ["routing"]


@respx.mock
async def test_create_reports_mismatch(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    posted = {}

    def on_post(request):
        posted["body"] = json.loads(request.content)
        return httpx.Response(200, json=saved(posted["body"]))

    def on_get(request):
        if not posted:
            return httpx.Response(200, json=rules())
        changed = saved({**posted["body"], "protocol": "tcp_udp"})
        changed["destination_filter"] = {**changed["destination_filter"], "port": "124"}
        return httpx.Response(200, json=rules() + [changed])

    respx.get(NAT).mock(side_effect=on_get)
    mock_lookups()
    respx.post(NAT).mock(side_effect=on_post)
    result = await create_nat_rule(mock_client, **ntp_args(), confirm=True)
    assert result["executed"] is True and result["verified"] is False
    assert result["mismatches"] == {
        "protocol": {"intended": "udp", "saved": "tcp_udp"},
        "destination_filter.port": {"intended": "123", "saved": "124"},
    }


@respx.mock
async def test_create_finds_rule_by_description_when_response_has_no_id(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    posted = {}

    def on_post(request):
        posted["body"] = json.loads(request.content)
        return httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"description": "x"}]})

    respx.get(NAT).mock(side_effect=lambda r: httpx.Response(
        200, json=rules() + ([saved(posted["body"])] if posted else [])))
    mock_lookups()
    respx.post(NAT).mock(side_effect=on_post)
    result = await create_nat_rule(mock_client, **ntp_args(), confirm=True)
    assert result["verified"] is True and result["rule"]["id"] == NEW_ID


@respx.mock
async def test_create_unverified_when_rule_not_found(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    respx.post(NAT).mock(return_value=httpx.Response(200, json={"_id": NEW_ID}))
    result = await create_nat_rule(mock_client, **ntp_args(), confirm=True)
    assert result["executed"] is True and result["verified"] is False
    assert "not found" in result["message"]


@respx.mock
async def test_create_empty_200_is_not_success(mock_client):
    from unifi_mcp.tools.network.nat_rules import create_nat_rule

    respx.get(NAT).mock(return_value=httpx.Response(200, json=rules()))
    mock_lookups()
    respx.post(NAT).mock(return_value=httpx.Response(200, json={}))
    result = await create_nat_rule(mock_client, **ntp_args(), confirm=True)
    assert result["executed"] is False
