"""Tests for group-aware product loaders, list_tool_groups, and the firmware drift report."""
import asyncio
import os
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.safety import SafetyManager, SafetyTier
from unifi_mcp.tools._registry import ProductRegistry, ToolModule, load_product_tools


@pytest.fixture(scope="module")
def server():
    """Import unifi_mcp.server with placeholder env vars if the real ones are absent."""
    with pytest.MonkeyPatch.context() as mp:
        if not os.environ.get("UNIFI_HOST"):
            mp.setenv("UNIFI_HOST", "https://192.0.2.1")
        if not os.environ.get("UNIFI_API_KEY"):
            mp.setenv("UNIFI_API_KEY", "test-key")
        import unifi_mcp.server as server_module
    return server_module


# --- fake tool modules ---

async def get_alpha(client) -> dict:
    """Get alpha."""
    return {"alpha": True}


async def set_alpha(client, alpha_id: str, confirm: bool = False) -> dict:
    """Set alpha (Tier 2)."""
    if not confirm:
        return {"preview": True, "action": "set_alpha", "alpha_id": alpha_id}
    return {"executed": True, "action": "set_alpha"}


async def get_beta(client) -> list[dict]:
    """Get beta."""
    return []


async def get_gamma(client) -> dict:
    """Get gamma."""
    return {}


FAKE_NETWORK = [
    ToolModule("network", "alpha", "core", (get_alpha, set_alpha),
               MappingProxyType({"set_alpha": "alpha"})),
    ToolModule("network", "beta", "security", (get_beta,)),
    ToolModule("network", "gamma", "insights", (get_gamma,)),
]


def _make_config(server, groups=None):
    from unifi_mcp.config import UnifiConfig

    return UnifiConfig(
        unifi_host="https://192.0.2.1", unifi_api_key="test-key", unifi_tool_groups=groups,
    )


@pytest.fixture
def isolated(server, monkeypatch):
    """Point the server's loader at a fresh FastMCP, registry, safety manager and fake modules."""
    from fastmcp import FastMCP

    state = SimpleNamespace(
        mcp=FastMCP("test-loading"),
        registry=ProductRegistry(),
        safety=SafetyManager(),
        probes=[],
        probe_result=True,
        modules={"network": list(FAKE_NETWORK), "protect": [], "access": []},
    )

    async def fake_probe(product):
        state.probes.append(product)
        await asyncio.sleep(0)
        return state.probe_result

    monkeypatch.setattr(server, "mcp", state.mcp)
    monkeypatch.setattr(server, "registry", state.registry)
    monkeypatch.setattr(server, "safety", state.safety)
    monkeypatch.setattr(server, "_probe_product", fake_probe)
    monkeypatch.setattr(server, "_load_lock", asyncio.Lock())
    monkeypatch.setattr(server, "config", _make_config(server))
    monkeypatch.setattr(server, "discover_tool_modules", lambda p: state.modules[p])
    return state


def _ctx():
    return SimpleNamespace(session=SimpleNamespace(send_tool_list_changed=AsyncMock()))


async def _tool_names(mcp) -> set[str]:
    return {tool.name for tool in await mcp.list_tools()}


def _fn(tool):
    return getattr(tool, "fn", tool)


# --- loaders ---

async def test_load_all_groups_by_default(server, isolated):
    ctx = _ctx()
    message = await _fn(server.load_network_tools)(ctx)
    assert message.startswith("Registered 4 network tools (groups: core, insights, security)")
    assert await _tool_names(isolated.mcp) == {"get_alpha", "set_alpha", "get_beta", "get_gamma"}
    ctx.session.send_tool_list_changed.assert_awaited_once()
    summary = isolated.registry.get_summary()["network"]
    assert summary == {"loaded": True, "tool_count": 4,
                       "groups": ["core", "insights", "security"]}


async def test_load_subset_then_add_groups_registers_only_new_tools(server, isolated):
    first = await _fn(server.load_network_tools)(_ctx(), groups=["core"])
    assert first.startswith("Registered 2 network tools (groups: core)")
    assert "not loaded: insights, security" in first
    assert await _tool_names(isolated.mcp) == {"get_alpha", "set_alpha"}

    ctx = _ctx()
    second = await _fn(server.load_network_tools)(ctx, groups=["core", "security"])
    assert second.startswith("Registered 1 network tools (groups: core, security)")
    assert await _tool_names(isolated.mcp) == {"get_alpha", "set_alpha", "get_beta"}
    ctx.session.send_tool_list_changed.assert_awaited_once()
    assert isolated.probes == ["network"]  # probed once, on first load
    assert isolated.registry.get_summary()["network"]["tool_count"] == 3


async def test_reload_same_groups_is_a_no_op(server, isolated):
    await _fn(server.load_network_tools)(_ctx(), groups=["core"])
    ctx = _ctx()
    again = await _fn(server.load_network_tools)(ctx, groups=["network:core"])
    assert again == "Network tools already loaded (groups: core)."
    ctx.session.send_tool_list_changed.assert_not_awaited()


async def test_unknown_group_registers_nothing_and_skips_probe(server, isolated):
    message = await _fn(server.load_network_tools)(_ctx(), groups=["core", "bogus"])
    assert "Unknown network tool group(s) in groups: bogus" in message
    assert "core, insights, security" in message
    assert await _tool_names(isolated.mcp) == set()
    assert isolated.probes == []
    assert isolated.registry.is_loaded("network") is False


async def test_env_default_groups(server, isolated, monkeypatch):
    monkeypatch.setattr(server, "config", _make_config(server, "network:security,protect:cameras"))
    message = await _fn(server.load_network_tools)(_ctx())
    assert message.startswith("Registered 1 network tools (groups: security)")
    assert await _tool_names(isolated.mcp) == {"get_beta"}


async def test_explicit_groups_override_env(server, isolated, monkeypatch):
    monkeypatch.setattr(server, "config", _make_config(server, "network:security"))
    await _fn(server.load_network_tools)(_ctx(), groups=["insights"])
    assert await _tool_names(isolated.mcp) == {"get_gamma"}


async def test_env_unknown_group_names_the_env_var(server, isolated, monkeypatch):
    monkeypatch.setattr(server, "config", _make_config(server, "network:nope"))
    message = await _fn(server.load_network_tools)(_ctx())
    assert "UNIFI_TOOL_GROUPS" in message and "nope" in message
    assert await _tool_names(isolated.mcp) == set()


async def test_product_not_installed(server, isolated):
    isolated.probe_result = False
    message = await _fn(server.load_network_tools)(_ctx())
    assert message == "UniFi Network is not installed on this console."
    assert await _tool_names(isolated.mcp) == set()
    assert isolated.registry.is_loaded("network") is False


async def test_load_merges_module_tiers_into_safety(server, isolated):
    assert isolated.safety.get_tier("set_alpha") == SafetyTier.EXECUTE
    await _fn(server.load_network_tools)(_ctx(), groups=["security"])
    # Tiers are merged for every module of the product, not only the loaded groups.
    assert isolated.safety.get_tier("set_alpha") == SafetyTier.PREVIEW_CONFIRM
    assert isolated.safety.get_category("set_alpha") == "alpha"


async def test_registered_tier2_tool_is_guarded(server, isolated):
    await _fn(server.load_network_tools)(_ctx(), groups=["core"])
    tool = await isolated.mcp.get_tool("set_alpha")
    refused = await tool.fn(alpha_id="a1", confirm=True)
    assert refused["category"] == "PREVIEW_REQUIRED"
    preview = await tool.fn(alpha_id="a1")
    assert preview["preview"] is True
    done = await tool.fn(alpha_id="a1", confirm=True)
    assert done["executed"] is True


async def test_concurrent_loads_register_each_tool_once(server, isolated):
    results = await asyncio.gather(
        _fn(server.load_network_tools)(_ctx(), groups=["core"]),
        _fn(server.load_network_tools)(_ctx(), groups=["core"]),
    )
    assert sum(r.startswith("Registered 2") for r in results) == 1
    assert sum("already loaded" in r for r in results) == 1
    assert isolated.registry.get_summary()["network"]["tool_count"] == 2


async def test_protect_loader_accepts_groups(server, isolated):
    async def get_cam(client) -> dict:
        """Get a camera."""
        return {}

    isolated.modules["protect"] = [ToolModule("protect", "cams", "cameras", (get_cam,))]
    message = await _fn(server.load_protect_tools)(_ctx(), groups=["cameras"])
    assert message.startswith("Registered 1 protect tools (groups: cameras)")
    bad = await _fn(server.load_protect_tools)(_ctx(), groups=["network:core"])
    assert "is for product 'network'" in bad


async def test_access_loader_with_no_modules(server, isolated):
    message = await _fn(server.load_access_tools)(_ctx())
    assert message.startswith("Registered 0 access tools (groups: none)")
    assert await _fn(server.load_access_tools)(_ctx()) == (
        "Access tools already loaded (groups: none)."
    )


async def test_real_network_modules_load_completely(server, monkeypatch):
    """With real auto-discovery, a default load registers every network tool once."""
    from fastmcp import FastMCP

    from unifi_mcp.tools._registry import discover_tool_modules

    fresh = FastMCP("test-real")
    monkeypatch.setattr(server, "mcp", fresh)
    monkeypatch.setattr(server, "registry", ProductRegistry())
    monkeypatch.setattr(server, "safety", SafetyManager())
    monkeypatch.setattr(server, "_load_lock", asyncio.Lock())
    monkeypatch.setattr(server, "config", _make_config(server))
    monkeypatch.setattr(server, "discover_tool_modules", discover_tool_modules)

    async def ok(product):
        return True

    monkeypatch.setattr(server, "_probe_product", ok)
    await _fn(server.load_network_tools)(_ctx())
    expected = {fn.__name__ for fn in load_product_tools("network")}
    assert await _tool_names(fresh) == expected


async def test_loader_schemas_expose_optional_groups(server):
    for name in ("load_network_tools", "load_protect_tools"):
        tool = await server.mcp.get_tool(name)
        props = tool.parameters["properties"]
        assert "groups" in props, name
        assert "ctx" not in props, name
        assert "groups" not in tool.parameters.get("required", []), name


async def test_list_tool_groups_is_always_registered(server):
    assert "list_tool_groups" in await _tool_names(server.mcp)


async def test_list_tool_groups_report(server, isolated, monkeypatch):
    monkeypatch.setattr(server, "config", _make_config(server, "network:core"))
    await _fn(server.load_network_tools)(_ctx())
    report = await _fn(server.list_tool_groups)()
    network = {g["group"]: g for g in report["products"]["network"]}
    assert network["core"]["loaded"] is True
    assert network["security"]["loaded"] is False
    assert set(network["core"]) == {"group", "modules", "tool_count", "loaded"}
    assert report["default_groups"] == "network:core"
    assert "load_network_tools" in report["usage"]
    assert set(report["products"]) == {"network", "protect", "access"}


async def test_list_tool_groups_default_is_all(server, isolated):
    report = await _fn(server.list_tool_groups)()
    assert report["default_groups"] == "all"


# --- firmware drift ---

@pytest.mark.parametrize("console, expected", [
    ({"network": "10.6.106", "protect": "7.2.105"}, []),
    ({"network": "10.6.200", "protect": "7.2.1"}, []),         # patch-level only
    ({"network": "10.7.1", "protect": "7.2.105"}, ["network"]),
    ({"network": "11.0.0", "protect": "7.3.70"}, ["network", "protect"]),
    ({"network": None, "protect": None}, []),                 # unknown is not drift
    ({"network": "garbage", "protect": "v7.4.0"}, ["protect"]),
    ({}, []),
])
def test_firmware_drift(server, console, expected):
    assert server.firmware_drift(console) == expected


def test_verified_versions_constant(server):
    assert server.VERIFIED_VERSIONS == {"network": "10.6.106", "protect": "7.2.105"}


class FakeVersionClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, path, cache_category=None, cache_ttl=None, params=None):
        self.calls.append((path, cache_category, cache_ttl))
        outcome = self.responses[path]
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


NET_INFO = "/proxy/network/integration/v1/info"
PROTECT_INFO = "/proxy/protect/integration/v1/meta/info"


async def test_console_versions_reads_both_products(server):
    fake = FakeVersionClient({
        NET_INFO: {"applicationVersion": "10.6.106"},
        PROTECT_INFO: {"applicationVersion": " 7.2.105 "},
    })
    assert await server.console_versions(fake) == {"network": "10.6.106", "protect": "7.2.105"}
    assert all(category == "server_info" and ttl and ttl <= 300
               for _, category, ttl in fake.calls)


@pytest.mark.parametrize("outcome", [
    UnifiError(ErrorCategory.NOT_FOUND, "nope"),
    RuntimeError("boom"),
    {"applicationVersion": ""},
    {"applicationVersion": 7},
    {"data": []},
    ["not", "a", "dict"],
])
async def test_console_versions_never_raises(server, outcome):
    fake = FakeVersionClient({NET_INFO: {"applicationVersion": "10.6.106"}, PROTECT_INFO: outcome})
    assert await server.console_versions(fake) == {"network": "10.6.106", "protect": None}


async def test_console_versions_times_out(server, monkeypatch):
    async def slow():
        await asyncio.sleep(5)
        return {"applicationVersion": "1.0.0"}

    monkeypatch.setattr(server, "_VERSION_TIMEOUT", 0.01)
    fake = FakeVersionClient({NET_INFO: slow, PROTECT_INFO: {"applicationVersion": "7.2.105"}})
    assert await server.console_versions(fake) == {"network": None, "protect": "7.2.105"}


async def test_console_versions_are_cached_by_the_client(server, monkeypatch):
    from unifi_mcp.auth.client import UnifiClient
    from unifi_mcp.auth.discovery import DiscoveryRegistry
    from unifi_mcp.cache import TTLCache

    real = UnifiClient(_make_config(server), TTLCache(), DiscoveryRegistry())
    with respx.mock(assert_all_called=True) as router:
        net = router.get(f"https://192.0.2.1{NET_INFO}").mock(
            return_value=httpx.Response(200, json={"applicationVersion": "10.6.106"}))
        prot = router.get(f"https://192.0.2.1{PROTECT_INFO}").mock(
            return_value=httpx.Response(404, json={"error": "not found"}))
        first = await server.console_versions(real)
        second = await server.console_versions(real)
    await real.close()
    assert first == second == {"network": "10.6.106", "protect": None}
    assert net.call_count == 1
    assert prot.call_count == 2  # failures are not cached


async def test_get_server_info_reports_drift(server, monkeypatch):
    fake = FakeVersionClient({
        NET_INFO: {"applicationVersion": "10.7.3"},
        PROTECT_INFO: {"applicationVersion": "7.2.110"},
    })
    monkeypatch.setattr(server, "client", fake)
    info = await _fn(server.get_server_info)()
    assert info["console_versions"] == {"network": "10.7.3", "protect": "7.2.110"}
    assert info["verified_versions"] == {"network": "10.6.106", "protect": "7.2.105"}
    assert info["drift"] == ["network"]
    assert "scripts/spec_diff.py" in info["drift_hint"]
    assert "10.7.3" in info["drift_hint"] and "10.6.106" in info["drift_hint"]
    for key in ("server", "version", "console", "site", "preview_ttl_seconds", "products"):
        assert key in info
    info["verified_versions"]["network"] = "0.0.0"
    assert server.VERIFIED_VERSIONS["network"] == "10.6.106"


async def test_get_server_info_survives_unreachable_console(server, monkeypatch):
    err = UnifiError(ErrorCategory.CONNECTION_ERROR, "unreachable")
    monkeypatch.setattr(server, "client", FakeVersionClient({NET_INFO: err, PROTECT_INFO: err}))
    info = await _fn(server.get_server_info)()
    assert info["console_versions"] == {"network": None, "protect": None}
    assert info["drift"] == []
    assert info["drift_hint"] is None


# --- product probe ---

class FakeProbeClient:
    def __init__(self, outcome):
        self.outcome = outcome
        self.paths = []

    async def get(self, path, **kwargs):
        self.paths.append(path)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize("outcome, expected", [
    ({"applicationVersion": "7.2.105"}, True),
    ([{"name": "x"}], True),
    ("<html>", False),
    (UnifiError(ErrorCategory.UNEXPECTED_RESPONSE, "html landing page"), False),
])
async def test_probe_product(server, monkeypatch, outcome, expected):
    fake = FakeProbeClient(outcome)
    monkeypatch.setattr(server, "client", fake)
    assert await server._probe_product("protect") is expected
    assert fake.paths == ["/proxy/protect/integration/v1/meta/info"]


async def test_probe_unknown_product_is_false(server, monkeypatch):
    fake = FakeProbeClient({})
    monkeypatch.setattr(server, "client", fake)
    assert await server._probe_product("cloud") is False
    assert fake.paths == []
