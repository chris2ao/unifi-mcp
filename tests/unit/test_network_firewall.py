import json
import pytest
import httpx
import respx
from pathlib import Path

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
@pytest.mark.asyncio
async def test_list_firewall_rules(mock_client):
    from unifi_mcp.tools.network.firewall import list_firewall_rules

    fixture = load_fixture("firewall_rules.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/firewallrule").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_firewall_rules(mock_client)
    assert len(result) == 2
    assert result[0]["name"] == "Block IoT to LAN"


@respx.mock
@pytest.mark.asyncio
async def test_create_firewall_rule_preview(mock_client):
    from unifi_mcp.tools.network.firewall import create_firewall_rule

    result = await create_firewall_rule(
        mock_client,
        name="Test Rule",
        action="drop",
        protocol="tcp",
        ruleset="LAN_IN",
        confirm=False,
    )
    assert result["preview"] is True
    assert result["action"] == "create_firewall_rule"


@respx.mock
@pytest.mark.asyncio
async def test_create_firewall_rule_confirmed(mock_client):
    from unifi_mcp.tools.network.firewall import create_firewall_rule

    respx.post("https://192.168.1.1/proxy/network/api/s/default/rest/firewallrule").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "fw_new", "name": "Test Rule"}]})
    )
    result = await create_firewall_rule(
        mock_client,
        name="Test Rule",
        action="drop",
        protocol="tcp",
        ruleset="LAN_IN",
        confirm=True,
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_firewall_rule_preview(mock_client):
    from unifi_mcp.tools.network.firewall import delete_firewall_rule

    result = await delete_firewall_rule(mock_client, rule_id="fw001", confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_list_firewall_groups(mock_client):
    from unifi_mcp.tools.network.firewall import list_firewall_groups

    fixture = load_fixture("firewall_groups.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/firewallgroup").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_firewall_groups(mock_client)
    assert len(result) == 2
    assert result[0]["name"] == "Trusted Servers"


@respx.mock
@pytest.mark.asyncio
async def test_create_firewall_group_preview(mock_client):
    from unifi_mcp.tools.network.firewall import create_firewall_group

    result = await create_firewall_group(
        mock_client,
        name="New Group",
        group_type="address-group",
        members=["10.0.0.1"],
        confirm=False,
    )
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_reorder_firewall_rules_preview(mock_client):
    from unifi_mcp.tools.network.firewall import reorder_firewall_rules

    result = await reorder_firewall_rules(
        mock_client, rule_id="fw001", new_index=500, confirm=False
    )
    assert result["preview"] is True
    assert result["action"] == "reorder_firewall_rules"


def test_firewall_tools_list():
    from unifi_mcp.tools.network.firewall import TOOLS
    assert len(TOOLS) == 8
