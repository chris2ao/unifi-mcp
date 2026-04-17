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


SITE_UUID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def mock_client(config):
    client = UnifiClient(config, TTLCache(), DiscoveryRegistry())
    client._site_id = SITE_UUID
    return client


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@respx.mock
@pytest.mark.asyncio
async def test_list_zbf_zones(mock_client):
    from unifi_mcp.tools.network.zbf import list_zbf_zones

    fixture = load_fixture("zbf_zones.json")
    respx.get(f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/firewall/zones").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_zbf_zones(mock_client)
    assert len(result) == 3
    assert result[0]["name"] == "Internal"


@respx.mock
@pytest.mark.asyncio
async def test_get_zbf_zone(mock_client):
    from unifi_mcp.tools.network.zbf import get_zbf_zone

    fixture = load_fixture("zbf_zones.json")
    respx.get(f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/firewall/zones/zone001").mock(
        return_value=httpx.Response(200, json={"data": fixture["data"][0]})
    )
    result = await get_zbf_zone(mock_client, zone_id="zone001")
    assert result["name"] == "Internal"
    assert len(result["networks"]) == 2


@respx.mock
@pytest.mark.asyncio
async def test_list_zbf_policies(mock_client):
    from unifi_mcp.tools.network.zbf import list_zbf_policies

    fixture = load_fixture("zbf_policies.json")
    respx.get("https://192.168.1.1/proxy/network/v2/api/site/default/firewall-policies").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_zbf_policies(mock_client)
    assert len(result) == 2
    assert result[0]["name"] == "Allow Internal to External"


@respx.mock
@pytest.mark.asyncio
async def test_create_zbf_policy_preview(mock_client):
    from unifi_mcp.tools.network.zbf import create_zbf_policy

    result = await create_zbf_policy(
        mock_client,
        name="Test Policy",
        source_zone_id="zone001",
        destination_zone_id="zone002",
        action="ALLOW",
        confirm=False,
    )
    assert result["preview"] is True
    assert result["action"] == "create_zbf_policy"


@respx.mock
@pytest.mark.asyncio
async def test_create_zbf_policy_confirmed(mock_client):
    from unifi_mcp.tools.network.zbf import create_zbf_policy

    respx.post("https://192.168.1.1/proxy/network/v2/api/site/default/firewall-policies").mock(
        return_value=httpx.Response(200, json={"data": {"_id": "pol_new", "name": "Test Policy"}})
    )
    result = await create_zbf_policy(
        mock_client,
        name="Test Policy",
        source_zone_id="zone001",
        destination_zone_id="zone002",
        action="ALLOW",
        confirm=True,
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_zbf_policy_preview(mock_client):
    from unifi_mcp.tools.network.zbf import delete_zbf_policy

    result = await delete_zbf_policy(mock_client, policy_id="pol001", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "delete_zbf_policy"


def test_zbf_tools_list():
    from unifi_mcp.tools.network.zbf import TOOLS
    assert len(TOOLS) == 6
