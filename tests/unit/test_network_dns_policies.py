import json
from pathlib import Path

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig

FIXTURES = Path(__file__).parent.parent / "fixtures"
SITE_UUID = "00000000-0000-0000-0000-000000000001"


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


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())

from unifi_mcp.tools.network import dns_policies as dp

BASE = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/dns/policies"
A_ID = "00000000-0000-0000-0000-0000000000a1"


def _a_body(**over):
    body = {"type": "A_RECORD", "enabled": True, "domain": "nas.example.com",
            "ipv4Address": "192.0.2.10", "ttlSeconds": 14400}
    return {**body, **over}


def test_module_declarations():
    assert dp.GROUP == "security"
    assert set(dp.TIER2_TOOLS) == {"create_dns_policy", "update_dns_policy", "delete_dns_policy"}
    assert set(dp.TIER2_TOOLS.values()) == {"dns"}
    assert [t.__name__ for t in dp.TOOLS] == [
        "list_dns_policies", "get_dns_policy", "create_dns_policy",
        "update_dns_policy", "delete_dns_policy",
    ]


@respx.mock
async def test_list_all(mock_client):
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("dns_policies.json")))
    result = await dp.list_dns_policies(mock_client)
    assert len(result) == 7
    assert result[0]["type"] == "A_RECORD" and result[0]["origin"] == "USER_DEFINED"
    assert "metadata" not in result[0]
    assert route.calls[0].request.url.params["offset"] == "0"
    assert "filter" not in route.calls[0].request.url.params


@respx.mock
async def test_list_type_and_filter(mock_client):
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_empty.json")))
    assert await dp.list_dns_policies(mock_client, type="CNAME_RECORD", filter="enabled.eq(true)") == []
    assert route.calls[0].request.url.params["filter"] == "and(type.eq('CNAME_RECORD'), enabled.eq(true))"


@respx.mock
async def test_list_type_only_and_filter_only(mock_client):
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_empty.json")))
    await dp.list_dns_policies(mock_client, type="A_RECORD")
    assert route.calls[0].request.url.params["filter"] == "type.eq('A_RECORD')"
    mock_client.cache.invalidate("dns")
    await dp.list_dns_policies(mock_client, filter="domain.like('*.example.com')")
    assert route.calls[1].request.url.params["filter"] == "domain.like('*.example.com')"


@respx.mock
async def test_list_bare_list_shape(mock_client):
    respx.get(BASE).mock(return_value=httpx.Response(200, json=load_fixture("dns_policies.json")["data"]))
    assert len(await dp.list_dns_policies(mock_client)) == 7


async def test_list_invalid_type(mock_client):
    result = await dp.list_dns_policies(mock_client, type="BOGUS")
    assert result["category"] == "VALIDATION_ERROR"


@respx.mock
async def test_get_policy(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    result = await dp.get_dns_policy(mock_client, A_ID)
    assert result["ipv4Address"] == "192.0.2.10" and result["ttlSeconds"] == 14400


@respx.mock
async def test_get_policy_wrapped_in_data(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(
        return_value=httpx.Response(200, json={"data": [load_fixture("dns_policies_a_record.json")]}))
    assert (await dp.get_dns_policy(mock_client, A_ID))["id"] == A_ID


@respx.mock
async def test_get_policy_not_found(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(404, json={"message": "nope"}))
    result = await dp.get_dns_policy(mock_client, A_ID)
    assert result["category"] == "NOT_FOUND" and result["policy_id"] == A_ID


@respx.mock
async def test_get_policy_empty_body_is_not_found(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await dp.get_dns_policy(mock_client, A_ID))["category"] == "NOT_FOUND"


@respx.mock
async def test_get_policy_other_error_propagates(mock_client):
    from unifi_mcp.errors import UnifiError
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(UnifiError):
        await dp.get_dns_policy(mock_client, A_ID)


@pytest.mark.parametrize("bad", ["", "a/b", "..", "x?y", "a b", "a#b"])
async def test_id_validation_everywhere(mock_client, bad):
    for result in (
        await dp.get_dns_policy(mock_client, bad),
        await dp.delete_dns_policy(mock_client, bad),
        await dp.update_dns_policy(mock_client, bad, {"enabled": False}),
    ):
        assert result["category"] == "VALIDATION_ERROR"


# ---- create ----

@respx.mock
async def test_create_preview_makes_no_call(mock_client):
    result = await dp.create_dns_policy(mock_client, "A_RECORD", "nas.example.com", ipv4_address="192.0.2.10")
    assert result["preview"] is True and result["action"] == "create_dns_policy"
    assert result["policy"] == _a_body()  # default ttl applied
    assert len(respx.calls) == 0
    again = await dp.create_dns_policy(mock_client, "A_RECORD", "nas.example.com", ipv4_address="192.0.2.10")
    assert again == result


CREATE_CASES = [
    ("A_RECORD", "a.example.com", {"ipv4_address": "192.0.2.1", "ttl_seconds": 60},
     {"ipv4Address": "192.0.2.1", "ttlSeconds": 60}),
    ("AAAA_RECORD", "a.example.com", {"ipv6_address": "2001:db8::1"},
     {"ipv6Address": "2001:db8::1", "ttlSeconds": 14400}),
    ("CNAME_RECORD", "www.example.com", {"target_domain": "a.example.com", "ttl_seconds": 604800},
     {"targetDomain": "a.example.com", "ttlSeconds": 604800}),
    ("MX_RECORD", "example.com", {"mail_server_domain": "mail.example.com", "priority": 10},
     {"mailServerDomain": "mail.example.com", "priority": 10}),
    ("TXT_RECORD", "example.com", {"text": "v=spf1 -all"}, {"text": "v=spf1 -all"}),
    ("SRV_RECORD", "example.com",
     {"server_domain": "s.example.com", "service": "_ldap", "protocol": "_tcp", "port": 389, "priority": 0, "weight": 5},
     {"serverDomain": "s.example.com", "service": "_ldap", "protocol": "_tcp", "port": 389, "priority": 0, "weight": 5}),
    ("FORWARD_DOMAIN", "corp.example.com", {"ip_address": "198.51.100.53"}, {"ipAddress": "198.51.100.53"}),
    ("FORWARD_DOMAIN", "corp.example.com", {"ip_address": "2001:db8::53"}, {"ipAddress": "2001:db8::53"}),
    ("A_RECORD", "*.lab.example.com", {"ipv4_address": "10.0.0.1"}, {"ipv4Address": "10.0.0.1", "ttlSeconds": 14400}),
]


@respx.mock
@pytest.mark.parametrize("dns_type,domain,kwargs,expected", CREATE_CASES)
async def test_create_confirmed_per_type(mock_client, dns_type, domain, kwargs, expected):
    route = respx.post(BASE).mock(return_value=httpx.Response(201, json={"id": A_ID, "type": dns_type}))
    mock_client.cache.set("dns:k", {"x": 1}, 60.0)
    result = await dp.create_dns_policy(mock_client, dns_type, domain, confirm=True, **kwargs)
    assert result["executed"] is True and result["action"] == "create_dns_policy"
    sent = json.loads(route.calls[0].request.content)
    assert sent == {"type": dns_type, "enabled": True, "domain": domain, **expected}
    assert mock_client.cache.get("dns:k") is None


@respx.mock
async def test_create_disabled(mock_client):
    route = respx.post(BASE).mock(return_value=httpx.Response(201, json={"id": A_ID}))
    await dp.create_dns_policy(mock_client, "TXT_RECORD", "example.com", text="x", enabled=False, confirm=True)
    assert json.loads(route.calls[0].request.content)["enabled"] is False


@respx.mock
async def test_create_silent_noop(mock_client):
    respx.post(BASE).mock(return_value=httpx.Response(200, json={"data": []}))
    result = await dp.create_dns_policy(mock_client, "TXT_RECORD", "example.com", text="x", confirm=True)
    assert result["executed"] is False and "message" in result


VALIDATION_CASES = [
    ("BOGUS", "a.example.com", {}),
    ("A_RECORD", "a.example.com", {}),                                         # missing ip
    ("A_RECORD", "a.example.com", {"ipv4_address": "999.1.1.1"}),
    ("A_RECORD", "a.example.com", {"ipv4_address": "2001:db8::1"}),
    ("A_RECORD", "a.example.com", {"ipv4_address": "192.0.2.1", "ttl_seconds": 86401}),
    ("A_RECORD", "a.example.com", {"ipv4_address": "192.0.2.1", "ttl_seconds": -1}),
    ("A_RECORD", "a.example.com", {"ipv4_address": "192.0.2.1", "ttl_seconds": True}),
    ("A_RECORD", "a.example.com", {"ipv4_address": "192.0.2.1", "text": "extra"}),  # wrong-type field
    ("A_RECORD", "", {"ipv4_address": "192.0.2.1"}),
    ("A_RECORD", "bad domain", {"ipv4_address": "192.0.2.1"}),
    ("A_RECORD", "a" * 128, {"ipv4_address": "192.0.2.1"}),
    ("A_RECORD", "-bad.example.com", {"ipv4_address": "192.0.2.1"}),
    ("AAAA_RECORD", "a.example.com", {"ipv6_address": "192.0.2.1"}),
    ("AAAA_RECORD", "a.example.com", {"ipv6_address": "nonsense"}),
    ("CNAME_RECORD", "a.example.com", {}),
    ("CNAME_RECORD", "a.example.com", {"target_domain": "t.example.com", "ttl_seconds": 604801}),
    ("CNAME_RECORD", "a.example.com", {"target_domain": "bad target"}),
    ("MX_RECORD", "example.com", {"mail_server_domain": "m.example.com"}),      # priority missing
    ("MX_RECORD", "example.com", {"mail_server_domain": "m.example.com", "priority": 70000}),
    ("TXT_RECORD", "example.com", {"text": ""}),
    ("TXT_RECORD", "example.com", {"text": "x" * 1025}),
    ("SRV_RECORD", "example.com", {"server_domain": "s.example.com", "service": "_ldap", "protocol": "_tcp",
                                   "port": 70000, "priority": 1, "weight": 1}),
    ("SRV_RECORD", "example.com", {"server_domain": "s.example.com", "service": "_ldap"}),
    ("SRV_RECORD", "example.com", {"server_domain": "s.example.com", "service": "bad service", "protocol": "_tcp",
                                  "port": 1, "priority": 1, "weight": 1}),
    ("FORWARD_DOMAIN", "corp.example.com", {}),
    ("FORWARD_DOMAIN", "corp.example.com", {"ip_address": "dns.example.com"}),
]


@respx.mock
@pytest.mark.parametrize("dns_type,domain,kwargs", VALIDATION_CASES)
@pytest.mark.parametrize("confirm", [False, True])
async def test_create_validation_errors(mock_client, dns_type, domain, kwargs, confirm):
    result = await dp.create_dns_policy(mock_client, dns_type, domain, confirm=confirm, **kwargs)
    assert result["error"] is True and result["category"] == "VALIDATION_ERROR"
    assert len(respx.calls) == 0


async def test_create_non_bool_enabled(mock_client):
    result = await dp.create_dns_policy(mock_client, "TXT_RECORD", "example.com", text="x", enabled="yes")
    assert result["category"] == "VALIDATION_ERROR"


# ---- update ----

@respx.mock
async def test_update_preview_reads_but_does_not_write(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    put = respx.put(f"{BASE}/{A_ID}")
    result = await dp.update_dns_policy(mock_client, A_ID, {"ipv4Address": "192.0.2.99"})
    assert result["preview"] is True
    assert result["policy"]["ipv4Address"] == "192.0.2.99"
    assert result["policy"]["domain"] == "nas.example.com"
    assert "id" not in result["policy"] and "metadata" not in result["policy"]
    assert result["current"]["ipv4Address"] == "192.0.2.10"
    assert not put.called
    assert await dp.update_dns_policy(mock_client, A_ID, {"ipv4Address": "192.0.2.99"}) == result


@respx.mock
async def test_update_confirmed_puts_full_merged_body(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    put = respx.put(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json={"id": A_ID}))
    result = await dp.update_dns_policy(mock_client, A_ID, {"ttl_seconds": 300, "enabled": False}, confirm=True)
    assert result["executed"] is True and result["policy_id"] == A_ID
    sent = json.loads(put.calls[0].request.content)
    assert sent == _a_body(ttlSeconds=300, enabled=False)


@respx.mock
async def test_update_does_not_mutate_input(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    updates = {"ttl_seconds": 300}
    await dp.update_dns_policy(mock_client, A_ID, updates)
    assert updates == {"ttl_seconds": 300}


@respx.mock
async def test_update_not_found(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(404, json={}))
    assert (await dp.update_dns_policy(mock_client, A_ID, {"enabled": False}))["category"] == "NOT_FOUND"


@respx.mock
async def test_update_silent_noop(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    respx.put(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json={"data": []}))
    result = await dp.update_dns_policy(mock_client, A_ID, {"enabled": False}, confirm=True)
    assert result["executed"] is False


@respx.mock
@pytest.mark.parametrize("updates", [
    {}, None, "x", {"type": "TXT_RECORD"}, {"id": "x"}, {"metadata": {}},
    {"ipv4Address": "bad"}, {"ttlSeconds": 999999}, {"text": "not allowed on A"},
])
async def test_update_validation(mock_client, updates):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    result = await dp.update_dns_policy(mock_client, A_ID, updates, confirm=True)
    assert result["category"] == "VALIDATION_ERROR"
    assert not any(c.request.method == "PUT" for c in respx.calls)


# ---- delete ----

@respx.mock
async def test_delete_preview_shows_record(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=load_fixture("dns_policies_a_record.json")))
    delete = respx.delete(f"{BASE}/{A_ID}")
    result = await dp.delete_dns_policy(mock_client, A_ID)
    assert result["preview"] is True and result["policy_id"] == A_ID
    assert result["policy"]["domain"] == "nas.example.com"
    assert not delete.called


@respx.mock
async def test_delete_preview_not_found(mock_client):
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(404, json={}))
    result = await dp.delete_dns_policy(mock_client, A_ID)
    assert result["category"] == "NOT_FOUND" and "preview" not in result


@respx.mock
async def test_update_ignores_unknown_response_fields(mock_client):
    record = {**load_fixture("dns_policies_a_record.json"), "description": "added by new firmware"}
    respx.get(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200, json=record))
    result = await dp.update_dns_policy(mock_client, A_ID, {"enabled": False})
    assert result["preview"] is True
    assert "description" not in result["policy"]


@respx.mock
async def test_delete_confirmed(mock_client):
    route = respx.delete(f"{BASE}/{A_ID}").mock(return_value=httpx.Response(200))
    result = await dp.delete_dns_policy(mock_client, A_ID, confirm=True)
    assert result["executed"] is True and result["response"] == {}
    assert route.called
