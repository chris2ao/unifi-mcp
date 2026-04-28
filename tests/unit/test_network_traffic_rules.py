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
COLLECTION_URL = "https://172.16.27.1/proxy/network/v2/api/site/default/trafficrules"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://172.16.27.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_rules(mock_client):
    from unifi_mcp.tools.network.traffic_rules import list_traffic_rules

    fixture = load_fixture("traffic_rules.json")
    respx.get(COLLECTION_URL).mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_traffic_rules(mock_client)
    assert len(result) == 2
    assert result[0]["description"] == "Block non-Pi-hole DNS - Default"
    assert result[0]["action"] == "BLOCK"
    assert result[1]["enabled"] is False


@respx.mock
@pytest.mark.asyncio
async def test_list_traffic_rules_bare_array(mock_client):
    from unifi_mcp.tools.network.traffic_rules import list_traffic_rules

    fixture = load_fixture("traffic_rules.json")
    respx.get(COLLECTION_URL).mock(
        return_value=httpx.Response(200, json=fixture["data"])
    )
    result = await list_traffic_rules(mock_client)
    assert len(result) == 2


@respx.mock
@pytest.mark.asyncio
async def test_get_traffic_rule_uses_collection(mock_client):
    """GET by id is 405; tool fetches collection and filters locally."""
    from unifi_mcp.tools.network.traffic_rules import get_traffic_rule

    fixture = load_fixture("traffic_rules.json")
    respx.get(COLLECTION_URL).mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_traffic_rule(mock_client, rule_id="tr_block_dns")
    assert result["id"] == "tr_block_dns"
    assert result["matching_target"] == "INTERNET"


@respx.mock
@pytest.mark.asyncio
async def test_get_traffic_rule_not_found(mock_client):
    from unifi_mcp.tools.network.traffic_rules import get_traffic_rule

    respx.get(COLLECTION_URL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await get_traffic_rule(mock_client, rule_id="tr_missing")
    assert result["error"] is True
    assert result["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_create_traffic_rule_preview(mock_client):
    from unifi_mcp.tools.network.traffic_rules import create_traffic_rule

    rule = {"description": "Test Rule", "action": "BLOCK", "enabled": True}
    result = await create_traffic_rule(mock_client, rule=rule, confirm=False)
    assert result["preview"] is True
    assert result["action"] == "create_traffic_rule"
    assert result["rule"] == rule


@respx.mock
@pytest.mark.asyncio
async def test_create_traffic_rule_confirmed(mock_client):
    from unifi_mcp.tools.network.traffic_rules import create_traffic_rule

    respx.post(COLLECTION_URL).mock(
        return_value=httpx.Response(200, json={"_id": "tr_new", "description": "Test Rule"})
    )
    rule = {"description": "Test Rule", "action": "BLOCK", "enabled": True}
    result = await create_traffic_rule(mock_client, rule=rule, confirm=True)
    assert result["executed"] is True
    assert result["action"] == "create_traffic_rule"


@respx.mock
@pytest.mark.asyncio
async def test_update_traffic_rule_preview(mock_client):
    from unifi_mcp.tools.network.traffic_rules import update_traffic_rule

    result = await update_traffic_rule(
        mock_client, rule_id="tr_block_dns", updates={"enabled": False}, confirm=False
    )
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_traffic_rule_confirmed(mock_client):
    from unifi_mcp.tools.network.traffic_rules import update_traffic_rule

    respx.put(f"{COLLECTION_URL}/tr_block_dns").mock(
        return_value=httpx.Response(200, json={"_id": "tr_block_dns", "enabled": False})
    )
    result = await update_traffic_rule(
        mock_client,
        rule_id="tr_block_dns",
        updates={"enabled": False, "description": "x"},
        confirm=True,
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_traffic_rule_preview(mock_client):
    from unifi_mcp.tools.network.traffic_rules import delete_traffic_rule

    result = await delete_traffic_rule(mock_client, rule_id="tr_block_dns", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "delete_traffic_rule"


@respx.mock
@pytest.mark.asyncio
async def test_delete_traffic_rule_confirmed_empty_body(mock_client):
    """UniFi returns an empty 200 on trafficrules DELETE; the client tolerates it."""
    from unifi_mcp.tools.network.traffic_rules import delete_traffic_rule

    respx.delete(f"{COLLECTION_URL}/tr_block_dns").mock(
        return_value=httpx.Response(200, content=b"")
    )
    result = await delete_traffic_rule(mock_client, rule_id="tr_block_dns", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_toggle_traffic_rule_preview(mock_client):
    from unifi_mcp.tools.network.traffic_rules import toggle_traffic_rule

    result = await toggle_traffic_rule(
        mock_client, rule_id="tr_block_dns", enabled=False, confirm=False
    )
    assert result["preview"] is True
    assert result["enabled"] is False


@respx.mock
@pytest.mark.asyncio
async def test_toggle_traffic_rule_confirmed(mock_client):
    """Toggle merges enabled into the existing rule body fetched from collection."""
    from unifi_mcp.tools.network.traffic_rules import toggle_traffic_rule

    fixture = load_fixture("traffic_rules.json")
    respx.get(COLLECTION_URL).mock(
        return_value=httpx.Response(200, json=fixture)
    )
    captured: dict = {}

    def _capture(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"_id": "tr_block_dns", "enabled": False})

    respx.put(f"{COLLECTION_URL}/tr_block_dns").mock(side_effect=_capture)

    result = await toggle_traffic_rule(
        mock_client, rule_id="tr_block_dns", enabled=False, confirm=True
    )
    assert result["executed"] is True
    assert captured["body"]["enabled"] is False
    assert captured["body"]["description"] == "Block non-Pi-hole DNS - Default"


def test_traffic_rules_tools_list():
    from unifi_mcp.tools.network.traffic_rules import TOOLS

    assert len(TOOLS) == 6
    names = [t.__name__ for t in TOOLS]
    assert names == [
        "list_traffic_rules",
        "get_traffic_rule",
        "create_traffic_rule",
        "update_traffic_rule",
        "delete_traffic_rule",
        "toggle_traffic_rule",
    ]
