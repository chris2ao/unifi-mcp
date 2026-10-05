import httpx
import pytest
import respx

from tests.unit.test_network_traffic_rules import load_fixture  # noqa: F401  (reuse loader)
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.cache import TTLCache
from unifi_mcp.config import UnifiConfig

BASE = "https://192.0.2.1/proxy/network"
ROUTES = f"{BASE}/v2/api/site/default/routes"
STATIC = f"{BASE}/api/s/default/rest/routing"
TRAFFIC = f"{BASE}/v2/api/site/default/trafficroutes"
NAT = f"{BASE}/v2/api/site/default/nat"


@pytest.fixture
def mock_client(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.0.2.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


def test_module_conventions():
    from unifi_mcp.tools.network import routing

    assert routing.GROUP == "insights"
    assert routing.TIER2_TOOLS == {}
    assert len(routing.TOOLS) == 4


@respx.mock
async def test_get_routing_table(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(200, json=load_fixture("routing_table.json")))
    result = await get_routing_table(mock_client)
    assert result["count"] == 2
    assert result["truncated"] is False
    assert result["routes"][0]["destination"] == "0.0.0.0/0"
    assert result["routes"][0]["nexthops"][0]["gateway"] == "198.51.100.1"
    assert result["routes"][1]["nexthops"][0]["interface"] == "br0"


@respx.mock
async def test_get_routing_table_truncated_and_bare_list(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(200, json={"items": [], "truncated": True}))
    result = await get_routing_table(mock_client)
    assert result == {"routes": [], "count": 0, "truncated": True}


@respx.mock
async def test_get_routing_table_bare_list(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    items = load_fixture("routing_table.json")["items"]
    respx.get(ROUTES).mock(return_value=httpx.Response(200, json=items))
    result = await get_routing_table(mock_client)
    assert result["count"] == 2 and result["truncated"] is False


@respx.mock
async def test_get_routing_table_tolerates_odd_items(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    payload = {"items": [{"destination": "1.0.0.0/8", "nexthops": None}, "junk"]}
    respx.get(ROUTES).mock(return_value=httpx.Response(200, json=payload))
    result = await get_routing_table(mock_client)
    assert result["count"] == 1
    assert result["routes"][0]["nexthops"] == []


@respx.mock
async def test_get_routing_table_404_fails_soft(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(404))
    result = await get_routing_table(mock_client)
    assert result["error"] is True
    assert result["category"] == "NOT_FOUND"
    assert "/v2/api/site/default/routes" in result["endpoint"]


@respx.mock
async def test_get_routing_table_shape_change_fails_soft(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(200, json={"unexpected": 1}))
    result = await get_routing_table(mock_client)
    assert result["error"] is True
    assert result["category"] == "UNEXPECTED_RESPONSE"
    assert "routes" in result["endpoint"]


@respx.mock
async def test_get_routing_table_string_payload_fails_soft(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(200, json="nope"))
    result = await get_routing_table(mock_client)
    assert result["category"] == "UNEXPECTED_RESPONSE"


@respx.mock
async def test_get_routing_table_items_not_list_fails_soft(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(200, json={"items": "x"}))
    result = await get_routing_table(mock_client)
    assert result["category"] == "UNEXPECTED_RESPONSE"


@respx.mock
async def test_get_routing_table_null_items(mock_client):
    from unifi_mcp.tools.network.routing import get_routing_table

    respx.get(ROUTES).mock(return_value=httpx.Response(200, json={"items": None}))
    result = await get_routing_table(mock_client)
    assert result["count"] == 0


@respx.mock
async def test_list_static_routes(mock_client):
    from unifi_mcp.tools.network.routing import list_static_routes

    respx.get(STATIC).mock(return_value=httpx.Response(200, json=load_fixture("routing_static_routes.json")))
    result = await list_static_routes(mock_client)
    assert len(result) == 2
    assert result[0]["network"] == "192.0.2.0/24"
    assert result[0]["next_hop"] == "10.0.0.2"
    assert result[0]["distance"] == 1


@respx.mock
async def test_list_static_routes_empty(mock_client):
    from unifi_mcp.tools.network.routing import list_static_routes

    respx.get(STATIC).mock(return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []}))
    assert await list_static_routes(mock_client) == []


@respx.mock
async def test_list_static_routes_auth_error(mock_client):
    from unifi_mcp.tools.network.routing import list_static_routes

    respx.get(STATIC).mock(return_value=httpx.Response(403))
    result = await list_static_routes(mock_client)
    assert result["category"] == "AUTH_ERROR"
    assert result["endpoint"].endswith("/rest/routing")


@respx.mock
async def test_list_traffic_routes(mock_client):
    from unifi_mcp.tools.network.routing import list_traffic_routes

    respx.get(TRAFFIC).mock(return_value=httpx.Response(200, json=load_fixture("routing_traffic_routes.json")))
    result = await list_traffic_routes(mock_client)
    assert result[0]["description"] == "Office via VPN"
    assert result[0]["kill_switch_enabled"] is True
    assert result[0]["domains"][0]["domain"] == "example.com"


@respx.mock
async def test_list_traffic_routes_empty_and_wrapped(mock_client):
    from unifi_mcp.tools.network.routing import list_traffic_routes

    route = respx.get(TRAFFIC)
    route.mock(return_value=httpx.Response(200, json=[]))
    assert await list_traffic_routes(mock_client) == []
    mock_client.cache.invalidate("routing")
    route.mock(return_value=httpx.Response(200, json={"data": [{"id": "x", "name": "n"}]}))
    result = await list_traffic_routes(mock_client)
    assert result[0]["id"] == "x" and result[0]["description"] == "n"


@respx.mock
async def test_list_traffic_routes_404(mock_client):
    from unifi_mcp.tools.network.routing import list_traffic_routes

    respx.get(TRAFFIC).mock(return_value=httpx.Response(404))
    result = await list_traffic_routes(mock_client)
    assert result["error"] is True and "trafficroutes" in result["endpoint"]


@respx.mock
async def test_list_nat_rules(mock_client):
    from unifi_mcp.tools.network.routing import list_nat_rules

    respx.get(NAT).mock(return_value=httpx.Response(200, json=load_fixture("routing_nat.json")))
    result = await list_nat_rules(mock_client)
    assert result[0]["type"] == "MASQUERADE"
    assert result[0]["out_interface"] == "eth8"


@respx.mock
async def test_list_nat_rules_empty(mock_client):
    from unifi_mcp.tools.network.routing import list_nat_rules

    respx.get(NAT).mock(return_value=httpx.Response(200, json=[]))
    assert await list_nat_rules(mock_client) == []


@respx.mock
async def test_list_nat_rules_404(mock_client):
    from unifi_mcp.tools.network.routing import list_nat_rules

    respx.get(NAT).mock(return_value=httpx.Response(404))
    result = await list_nat_rules(mock_client)
    assert result["category"] == "NOT_FOUND" and result["endpoint"].endswith("/nat")


@respx.mock
async def test_connection_error_fails_soft(mock_client):
    from unifi_mcp.tools.network.routing import list_nat_rules

    respx.get(NAT).mock(side_effect=httpx.ConnectError("down"))
    result = await list_nat_rules(mock_client)
    assert result["category"] == "CONNECTION_ERROR"


@respx.mock
async def test_static_route_reports_route_type(mock_client):
    from unifi_mcp.tools.network.routing import list_static_routes

    respx.get(STATIC).mock(return_value=httpx.Response(200, json=load_fixture("routing_static_routes.json")))
    result = await list_static_routes(mock_client)
    blackhole = next(r for r in result if r["name"] == "Blackhole")
    assert blackhole["route_type"] == "blackhole"
