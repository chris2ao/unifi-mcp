"""Tests for ACL rule ordering tools in mac_acl.py."""

import json

import httpx
import pytest
import respx

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig

SITE_UUID = "00000000-0000-0000-0000-000000000001"
URL = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/acl-rules/ordering"
A, B, C = (f"00000000-0000-0000-0000-0000000000b{n}" for n in (1, 2, 3))


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    client = UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def test_mac_acl_declarations():
    from unifi_mcp.tools.network import mac_acl

    assert mac_acl.TIER2_TOOLS == {
        "add_mac_filter": "mac_acl", "delete_mac_filter": "mac_acl", "reorder_acl_rules": "mac_acl",
    }
    assert {"get_acl_rule_order", "reorder_acl_rules"} <= {t.__name__ for t in mac_acl.TOOLS}


@respx.mock
@pytest.mark.asyncio
async def test_get_acl_rule_order(mock_client):
    from unifi_mcp.tools.network.mac_acl import get_acl_rule_order

    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B]}))
    assert await get_acl_rule_order(mock_client) == {"ordered_rule_ids": [A, B], "count": 2}


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"orderedAclRuleIds": []}, {}, [], {"data": {"orderedAclRuleIds": [A]}}])
async def test_get_acl_rule_order_shape_variance(mock_client, body):
    from unifi_mcp.tools.network.mac_acl import get_acl_rule_order

    respx.get(URL).mock(return_value=httpx.Response(200, json=body))
    result = await get_acl_rule_order(mock_client)
    assert result["count"] == len(result["ordered_rule_ids"])


@respx.mock
@pytest.mark.asyncio
async def test_get_acl_rule_order_bare_list(mock_client):
    from unifi_mcp.tools.network.mac_acl import get_acl_rule_order

    respx.get(URL).mock(return_value=httpx.Response(200, json=[A, B]))
    assert (await get_acl_rule_order(mock_client))["ordered_rule_ids"] == [A, B]


@respx.mock
@pytest.mark.asyncio
async def test_reorder_preview_has_impact_and_no_write(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B, C]}))
    put = respx.put(URL).mock(return_value=httpx.Response(200, json={}))
    result = await reorder_acl_rules(mock_client, [C, A, B])
    assert result["preview"] is True
    assert result["action"] == "reorder_acl_rules"
    assert result["current_order"] == [A, B, C]
    assert result["new_order"] == [C, A, B]
    assert result["changed"] is True
    assert "impact" in result and "evaluated first" in result["impact"]
    assert put.call_count == 0


@respx.mock
@pytest.mark.asyncio
async def test_reorder_preview_unchanged_flag_and_deterministic(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B]}))
    first = await reorder_acl_rules(mock_client, [A, B])
    assert first["changed"] is False
    assert first == await reorder_acl_rules(mock_client, [A, B])


@respx.mock
@pytest.mark.asyncio
async def test_reorder_confirm_executes(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    mock_client.cache.set("mac_acl:stale", {"x": 1}, 60.0)
    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B]}))
    put = respx.put(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [B, A]}))
    result = await reorder_acl_rules(mock_client, [B, A], confirm=True)
    assert result["executed"] is True
    assert result["new_order"] == [B, A]
    assert json.loads(put.calls.last.request.content) == {"orderedAclRuleIds": [B, A]}
    assert mock_client.cache.get("mac_acl:stale") is None


@respx.mock
@pytest.mark.asyncio
async def test_reorder_confirm_empty_response_verifies_with_get(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(
        side_effect=[
            httpx.Response(200, json={"orderedAclRuleIds": [A, B]}),
            httpx.Response(200, json={"orderedAclRuleIds": [B, A]}),
        ]
    )
    respx.put(URL).mock(return_value=httpx.Response(200, json={}))
    result = await reorder_acl_rules(mock_client, [B, A], confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_reorder_confirm_silent_noop(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B]}))
    respx.put(URL).mock(return_value=httpx.Response(200, json={}))
    result = await reorder_acl_rules(mock_client, [B, A], confirm=True)
    assert result["executed"] is False
    assert result["applied_order"] == [A, B]


@respx.mock
@pytest.mark.asyncio
async def test_reorder_rejects_set_mismatch(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B]}))
    put = respx.put(URL).mock(return_value=httpx.Response(200, json={}))
    missing = await reorder_acl_rules(mock_client, [A], confirm=True)
    assert missing["category"] == "VALIDATION_ERROR" and B in missing["message"]
    unknown = await reorder_acl_rules(mock_client, [A, B, C], confirm=True)
    assert unknown["category"] == "VALIDATION_ERROR" and C in unknown["message"]
    assert put.call_count == 0


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[], "abc", None, [A, A], [A, "../x"], [A, 5]])
async def test_reorder_rejects_bad_input(mock_client, bad):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(return_value=httpx.Response(200, json={"orderedAclRuleIds": [A, B]}))
    assert (await reorder_acl_rules(mock_client, bad))["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_reorder_read_error_is_structured(mock_client):
    from unifi_mcp.tools.network.mac_acl import reorder_acl_rules

    respx.get(URL).mock(return_value=httpx.Response(404, json={}))
    assert (await reorder_acl_rules(mock_client, [A]))["category"] == "NOT_FOUND"
