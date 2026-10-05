import json
import pytest
import httpx
import respx
from pathlib import Path

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry

SITE_UUID = "00000000-0000-0000-0000-000000000001"
FIXTURES = Path(__file__).parent.parent / "fixtures"


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


@respx.mock
@pytest.mark.asyncio
async def test_list_networks(mock_client):
    from unifi_mcp.tools.network.networks import list_networks

    fixture = load_fixture("networks.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await list_networks(mock_client)
    assert len(result) == 3
    assert result[0]["name"] == "Default"
    assert result[1]["name"] == "IoT"
    assert result[1]["vlan"] == 10


@respx.mock
@pytest.mark.asyncio
async def test_get_network(mock_client):
    from unifi_mcp.tools.network.networks import get_network

    fixture = load_fixture("networks.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/net002").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [fixture["data"][1]]})
    )
    result = await get_network(mock_client, network_id="net002")
    assert result["name"] == "IoT"
    assert result["vlan"] == 10


@respx.mock
@pytest.mark.asyncio
async def test_get_network_returns_not_found_for_unknown_id(mock_client):
    from unifi_mcp.tools.network.networks import get_network

    respx.get("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/missing").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await get_network(mock_client, network_id="missing")
    assert result["error"] is True
    assert result["category"] == "NOT_FOUND"
    assert result["network_id"] == "missing"


@respx.mock
@pytest.mark.asyncio
async def test_create_network_preview(mock_client):
    from unifi_mcp.tools.network.networks import create_network

    result = await create_network(
        mock_client,
        name="TestNet",
        purpose="corporate",
        subnet="192.168.50.0/24",
        vlan=50,
        confirm=False,
    )
    assert result["preview"] is True
    assert result["action"] == "create_network"
    assert result["params"]["name"] == "TestNet"


@respx.mock
@pytest.mark.asyncio
async def test_create_network_confirmed(mock_client):
    from unifi_mcp.tools.network.networks import create_network

    respx.post("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [{"_id": "net_new", "name": "TestNet"}]})
    )
    result = await create_network(
        mock_client,
        name="TestNet",
        purpose="corporate",
        subnet="192.168.50.0/24",
        vlan=50,
        confirm=True,
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_preview(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    result = await delete_network(mock_client, network_id="net002", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "delete_network"
    # Lookup is best effort: unmocked routes must not break the preview.
    assert "references" not in result
    assert "references_note" in result


@respx.mock
@pytest.mark.asyncio
async def test_get_dhcp_leases(mock_client):
    from unifi_mcp.tools.network.networks import get_dhcp_leases

    fixture = load_fixture("clients.json")
    respx.get("https://192.168.1.1/proxy/network/api/s/default/stat/sta").mock(
        return_value=httpx.Response(200, json=fixture)
    )
    result = await get_dhcp_leases(mock_client, network_id="net001")
    assert isinstance(result, list)
    # All 3 fixture clients are on net001
    assert len(result) == 3


def test_networks_tools_list():
    from unifi_mcp.tools.network.networks import TOOLS
    assert len(TOOLS) == 7


NET_BASE = f"https://192.168.1.1/proxy/network/integration/v1/sites/{SITE_UUID}/networks"
UUID_NET = "00000000-0000-0000-0000-0000000000c1"
LEGACY_URL = "https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/net001"


def _mock_mapping():
    respx.get(LEGACY_URL).mock(return_value=httpx.Response(
        200, json={"meta": {"rc": "ok"}, "data": [{"_id": "net001", "name": "Default"}]}))
    respx.get(NET_BASE).mock(return_value=httpx.Response(
        200, json=load_fixture("network_references_integration_networks.json")))


def test_networks_tier2_declaration():
    from unifi_mcp.tools.network.networks import TIER2_TOOLS
    assert TIER2_TOOLS == {
        "create_network": "networks", "update_network": "networks", "delete_network": "networks",
    }


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_integration_id(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(
        return_value=httpx.Response(200, json=load_fixture("network_references.json")))
    r = await get_network_references(mock_client, UUID_NET)
    assert r["referenced"] is True
    assert r["total_references"] == 3
    assert r["groups"][0] == {
        "resource_type": "DEVICE", "count": 2,
        "ids": ["00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2"],
    }
    assert r["groups"][1]["resource_type"] == "WIFI"


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_legacy_id_mapped_by_name(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    _mock_mapping()
    route = respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(
        return_value=httpx.Response(200, json=load_fixture("network_references.json")))
    r = await get_network_references(mock_client, "net001")
    assert route.called
    assert r["network_id"] == "net001"
    assert r["total_references"] == 3


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_empty(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(
        return_value=httpx.Response(200, json=load_fixture("network_references_empty.json")))
    r = await get_network_references(mock_client, UUID_NET)
    assert r["referenced"] is False and r["groups"] == []


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_wrapped_and_truncated(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    refs = [{"referenceId": f"id{i}"} for i in range(30)]
    body = {"data": {"referenceResources": [
        {"resourceType": "CLIENT", "referenceCount": 30, "references": refs},
        {"resourceType": "NAT_RULE", "references": [{"referenceId": "n1"}]},
        "junk",
    ]}}
    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(return_value=httpx.Response(200, json=body))
    r = await get_network_references(mock_client, UUID_NET)
    assert r["groups"][0]["count"] == 30 and len(r["groups"][0]["ids"]) == 20
    assert r["groups"][1]["count"] == 1
    assert r["total_references"] == 31


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_unexpected_shape(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(return_value=httpx.Response(200, json=[]))
    r = await get_network_references(mock_client, UUID_NET)
    assert r["referenced"] is False


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_404(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(return_value=httpx.Response(404))
    r = await get_network_references(mock_client, UUID_NET)
    assert r["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_legacy_unknown(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    respx.get(LEGACY_URL).mock(return_value=httpx.Response(200, json={"data": []}))
    r = await get_network_references(mock_client, "net001")
    assert r["category"] == "NOT_FOUND"


@respx.mock
@pytest.mark.asyncio
async def test_get_network_references_legacy_name_not_in_integration(mock_client):
    from unifi_mcp.tools.network.networks import get_network_references

    respx.get(LEGACY_URL).mock(return_value=httpx.Response(
        200, json={"data": [{"_id": "net001", "name": "Ghost"}]}))
    respx.get(NET_BASE).mock(return_value=httpx.Response(
        200, json=load_fixture("network_references_integration_networks.json")))
    r = await get_network_references(mock_client, "net001")
    assert r["category"] == "NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "a/b", "../x", "x?y", "a b"])
async def test_get_network_references_validation(mock_client, bad):
    from unifi_mcp.tools.network.networks import get_network_references

    r = await get_network_references(mock_client, bad)
    assert r["category"] == "VALIDATION_ERROR"


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_preview_lists_references(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    _mock_mapping()
    delete = respx.delete("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/net001")
    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(
        return_value=httpx.Response(200, json=load_fixture("network_references.json")))
    r = await delete_network(mock_client, network_id="net001")
    assert r["preview"] is True
    assert r["references"][0]["resource_type"] == "DEVICE"
    assert "still referenced by 3" in r["warning"]
    assert not delete.called
    assert await delete_network(mock_client, network_id="net001") == r


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_preview_unreferenced_has_no_warning(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(
        return_value=httpx.Response(200, json=load_fixture("network_references_empty.json")))
    r = await delete_network(mock_client, network_id=UUID_NET)
    assert r["references"] == []
    assert "warning" not in r


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_preview_lookup_not_found_noted(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(return_value=httpx.Response(404))
    r = await delete_network(mock_client, network_id=UUID_NET)
    assert r["preview"] is True
    assert "unavailable" in r["references_note"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_preview_lookup_crash_noted(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    respx.get(f"{NET_BASE}/{UUID_NET}/references").mock(side_effect=httpx.ConnectError("boom"))
    r = await delete_network(mock_client, network_id=UUID_NET)
    assert r["preview"] is True
    assert "lookup failed" in r["references_note"]


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_confirmed_skips_lookup(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    respx.delete("https://192.168.1.1/proxy/network/api/s/default/rest/networkconf/net001").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []}))
    r = await delete_network(mock_client, network_id="net001", confirm=True)
    assert r["executed"] is True
