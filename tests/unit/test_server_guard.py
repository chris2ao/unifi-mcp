"""Tests for the server registration wrapper: enforced preview-confirm and path-arg checks."""
import inspect
import os

import pytest

from unifi_mcp.safety import SafetyManager


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


class FakeClock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


class FakeTools:
    """Fake tool functions that record every invocation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.client_seen = None

    async def update_thing(
        self, client, thing_id: str, value: int = 1, note: str | None = None,
        confirm: bool = False,
    ) -> dict:
        """Update a thing (fake Tier 2 tool)."""
        self.client_seen = client
        self.calls.append(("update_thing", {"thing_id": thing_id, "value": value,
                                            "confirm": confirm}))
        if not confirm:
            return {"preview": True, "action": "update_thing", "thing_id": thing_id,
                    "value": value}
        return {"executed": True, "action": "update_thing", "response": {"ok": True}}

    async def failing_delete(self, client, thing_id: str, confirm: bool = False) -> dict:
        self.calls.append(("failing_delete", {"thing_id": thing_id, "confirm": confirm}))
        if not confirm:
            return {"preview": True, "action": "failing_delete", "thing_id": thing_id}
        raise RuntimeError("console exploded")

    async def error_preview(self, client, thing_id: str, confirm: bool = False) -> dict:
        self.calls.append(("error_preview", {"thing_id": thing_id, "confirm": confirm}))
        return {"error": True, "category": "PRODUCT_UNAVAILABLE", "message": "nope"}

    async def read_thing(self, client, thing_id: str) -> dict:
        self.calls.append(("read_thing", {"thing_id": thing_id}))
        return {"id": thing_id}

    async def list_things(self, client, site_mac: str | None = None) -> list[dict]:
        self.calls.append(("list_things", {"site_mac": site_mac}))
        return [{"id": "a"}]

    async def set_secret(self, client, name: str, x_passphrase: str,
                         confirm: bool = False) -> dict:
        self.calls.append(("set_secret", {"name": name, "confirm": confirm}))
        if not confirm:
            return {"preview": True, "action": "set_secret", "name": name}
        return {"executed": True, "action": "set_secret"}


def _as_tool(bound_method, name):
    """Turn a bound FakeTools method into a plain coroutine function named `name`."""
    async def tool(client, *args, **kwargs):
        return await bound_method(client, *args, **kwargs)

    sig = inspect.signature(bound_method)
    tool.__signature__ = sig
    tool.__name__ = name
    tool.__qualname__ = name
    tool.__doc__ = bound_method.__doc__
    tool.__annotations__ = dict(bound_method.__annotations__)
    return tool


@pytest.fixture
def env(server):
    clock = FakeClock()
    safety = SafetyManager(preview_ttl_seconds=600, clock=clock)
    fakes = FakeTools()
    client = object()

    def wrap(method_name):
        tool = _as_tool(getattr(fakes, method_name), method_name)
        return server.build_tool_wrapper(tool, client=client, safety=safety)

    return {"wrap": wrap, "fakes": fakes, "safety": safety, "clock": clock,
            "client": client}


def _executions(fakes, name):
    return [c for c in fakes.calls if c[0] == name and c[1].get("confirm")]


# --- preview-confirm enforcement ---

async def test_preview_then_confirm_succeeds(env):
    tool = env["wrap"]("update_thing")
    preview = await tool(thing_id="t1", value=5)
    assert preview["preview"] is True
    result = await tool(thing_id="t1", value=5, confirm=True)
    assert result["executed"] is True
    assert len(_executions(env["fakes"], "update_thing")) == 1
    assert env["fakes"].client_seen is env["client"]


async def test_confirm_without_preview_is_refused_and_tool_not_called(env):
    tool = env["wrap"]("update_thing")
    result = await tool(thing_id="t1", value=5, confirm=True)
    assert result["error"] is True
    assert result["category"] == "PREVIEW_REQUIRED"
    assert "update_thing" in result["message"]
    assert "confirm=False" in result["message"]
    assert env["fakes"].calls == []


async def test_changed_params_refused(env):
    tool = env["wrap"]("update_thing")
    await tool(thing_id="t1", value=5)
    result = await tool(thing_id="t1", value=6, confirm=True)
    assert result["category"] == "PREVIEW_REQUIRED"
    assert _executions(env["fakes"], "update_thing") == []
    # The original preview is still usable for the original params.
    ok = await tool(thing_id="t1", value=5, confirm=True)
    assert ok["executed"] is True


async def test_defaults_and_positional_args_hash_identically(env):
    tool = env["wrap"]("update_thing")
    await tool("t1")
    result = await tool(thing_id="t1", value=1, note=None, confirm=True)
    assert result["executed"] is True


async def test_preview_of_other_tool_does_not_count(env):
    update = env["wrap"]("update_thing")
    delete = env["wrap"]("failing_delete")
    await delete(thing_id="t1")
    result = await update(thing_id="t1", confirm=True)
    assert result["category"] == "PREVIEW_REQUIRED"


async def test_expired_preview_refused(env):
    tool = env["wrap"]("update_thing")
    await tool(thing_id="t1")
    env["clock"].now += 601
    result = await tool(thing_id="t1", confirm=True)
    assert result["category"] == "PREVIEW_REQUIRED"
    assert _executions(env["fakes"], "update_thing") == []


async def test_preview_is_single_use(env):
    tool = env["wrap"]("update_thing")
    await tool(thing_id="t1")
    first = await tool(thing_id="t1", confirm=True)
    second = await tool(thing_id="t1", confirm=True)
    assert first["executed"] is True
    assert second["category"] == "PREVIEW_REQUIRED"
    assert len(_executions(env["fakes"], "update_thing")) == 1


async def test_preview_consumed_even_when_execution_fails(env):
    tool = env["wrap"]("failing_delete")
    await tool(thing_id="t1")
    with pytest.raises(RuntimeError):
        await tool(thing_id="t1", confirm=True)
    retry = await tool(thing_id="t1", confirm=True)
    assert retry["category"] == "PREVIEW_REQUIRED"
    log = env["safety"].get_mutation_log()
    assert log[-1]["tool"] == "failing_delete"
    assert log[-1]["result"]["error"] is True
    assert log[-1]["result"]["exception"] == "RuntimeError"


async def test_error_preview_is_not_recorded(env):
    tool = env["wrap"]("error_preview")
    first = await tool(thing_id="t1")
    assert first["category"] == "PRODUCT_UNAVAILABLE"
    result = await tool(thing_id="t1", confirm=True)
    assert result["category"] == "PREVIEW_REQUIRED"


async def test_confirmed_execution_is_audited_with_masked_params(env):
    tool = env["wrap"]("set_secret")
    await tool(name="Guest", x_passphrase="hunter2")
    result = await tool(name="Guest", x_passphrase="hunter2", confirm=True)
    assert result["executed"] is True
    log = env["safety"].get_mutation_log()
    assert len(log) == 1
    entry = log[0]
    assert entry["tool"] == "set_secret"
    assert entry["params"] == {"name": "Guest", "x_passphrase": "***"}
    assert entry["result"] == {"executed": True, "action": "set_secret"}
    assert "hunter2" not in repr(log)


async def test_previews_are_not_audited(env):
    tool = env["wrap"]("update_thing")
    await tool(thing_id="t1")
    assert env["safety"].get_mutation_log() == []


async def test_confirm_false_explicit_is_preview(env):
    tool = env["wrap"]("update_thing")
    result = await tool(thing_id="t1", confirm=False)
    assert result["preview"] is True
    assert env["safety"].has_preview("update_thing")


async def test_bad_arguments_return_validation_error(env):
    tool = env["wrap"]("update_thing")
    result = await tool(bogus=1)
    assert result["category"] == "VALIDATION_ERROR"
    assert env["fakes"].calls == []


# --- non-guarded tools ---

async def test_non_guarded_tool_runs_directly(env):
    tool = env["wrap"]("read_thing")
    assert await tool(thing_id="t1") == {"id": "t1"}
    assert await tool("t2") == {"id": "t2"}
    assert len(env["fakes"].calls) == 2
    assert env["safety"].get_mutation_log() == []


# --- path-segment defense in depth ---

@pytest.mark.parametrize("bad", [
    "../x", "a/b", "a\\b", "a?b", "a#b", "a b", "a\tb", "a\nb", "a\x00b", "a\x7fb", "..", "%2e%2e", "a%2Fb", "%2e%2e%2fx",
])
async def test_path_segment_rejected_for_id_params(env, bad):
    read = env["wrap"]("read_thing")
    update = env["wrap"]("update_thing")
    result = await read(thing_id=bad)
    assert result["category"] == "VALIDATION_ERROR"
    assert "thing_id" in result["message"]
    preview = await update(thing_id=bad)
    assert preview["category"] == "VALIDATION_ERROR"
    assert env["fakes"].calls == []


async def test_path_segment_rejected_for_mac_param_on_list_tool(env):
    tool = env["wrap"]("list_things")
    result = await tool(site_mac="aa:bb/cc")
    # List-returning tools get the error wrapped in a list to match their schema.
    assert isinstance(result, list)
    assert result[0]["category"] == "VALIDATION_ERROR"
    assert env["fakes"].calls == []
    assert await tool(site_mac="aa:bb:cc:00:00:01") == [{"id": "a"}]
    assert await tool() == [{"id": "a"}]


async def test_valid_ids_pass(env):
    tool = env["wrap"]("read_thing")
    for good in ("abc", "00000000-0000-0000-0000-0000000000a1", "aa:bb:cc:00:00:01",
                 "file_v1.2.unf"):
        assert await tool(thing_id=good) == {"id": good}


def test_is_path_param(server):
    assert server._is_path_param("id")
    assert server._is_path_param("mac")
    assert server._is_path_param("camera_id")
    assert server._is_path_param("client_mac")
    assert not server._is_path_param("name")
    assert not server._is_path_param("identity")


# --- signature handling ---

def test_wrapper_hides_client_and_keeps_signature(env):
    tool = env["wrap"]("update_thing")
    params = inspect.signature(tool).parameters
    assert "client" not in params
    assert list(params) == ["thing_id", "value", "note", "confirm"]
    assert "client" not in tool.__annotations__
    assert tool.__name__ == "update_thing"


def test_bind_client_uses_module_singletons(server):
    async def demo_tool(client, thing_id: str) -> dict:
        return {"client_is_module_client": client is server.client}

    wrapped = server._bind_client(demo_tool)
    assert "client" not in inspect.signature(wrapped).parameters


async def test_bind_client_passes_module_client(server):
    async def demo_tool(client, thing_id: str) -> dict:
        return {"same": client is server.client}

    assert await server._bind_client(demo_tool)(thing_id="x") == {"same": True}


# --- end to end through FastMCP ---

async def test_guard_through_fastmcp_client(server, env):
    from fastmcp import Client, FastMCP

    app = FastMCP("guard-test")
    app.tool()(env["wrap"]("update_thing"))
    async with Client(app) as mcp_client:
        tools = {t.name: t for t in await mcp_client.list_tools()}
        assert "client" not in tools["update_thing"].inputSchema["properties"]
        refused = await mcp_client.call_tool(
            "update_thing", {"thing_id": "t1", "confirm": True},
        )
        assert refused.data["category"] == "PREVIEW_REQUIRED"
        await mcp_client.call_tool("update_thing", {"thing_id": "t1"})
        done = await mcp_client.call_tool(
            "update_thing", {"thing_id": "t1", "confirm": True},
        )
        assert done.data["executed"] is True


# --- always-loaded utility tools ---

async def test_get_mutation_log_tool_masks(server, monkeypatch):
    manager = SafetyManager()
    manager.log_mutation("create_wlan", {"name": "Guest", "x_passphrase": "p"},
                         {"executed": True})
    monkeypatch.setattr(server, "safety", manager)
    fn = getattr(server.get_mutation_log, "fn", server.get_mutation_log)
    log = await fn()
    assert log[0]["params"]["x_passphrase"] == "***"
    assert log[0]["tool"] == "create_wlan"


async def test_get_server_info_reports_package_version(server, monkeypatch):
    import unifi_mcp

    async def no_console(api_client):
        return {"network": None, "protect": None}

    # Never reach a real console from a unit test.
    monkeypatch.setattr(server, "console_versions", no_console)
    fn = getattr(server.get_server_info, "fn", server.get_server_info)
    info = await fn()
    assert info["version"] == unifi_mcp.__version__
    assert info["version"] != "0.2.1"
    assert info["preview_ttl_seconds"] == server.config.unifi_preview_ttl_seconds


def test_module_safety_uses_config_ttl(server):
    assert server.safety.preview_ttl_seconds == server.config.unifi_preview_ttl_seconds


# --- real tools through the wrapper ---

@pytest.fixture
def mock_client(monkeypatch):
    from unifi_mcp.auth.client import UnifiClient
    from unifi_mcp.auth.discovery import DiscoveryRegistry
    from unifi_mcp.cache import TTLCache
    from unifi_mcp.config import UnifiConfig

    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    monkeypatch.setenv("UNIFI_SITE", "default")
    return UnifiClient(UnifiConfig(), TTLCache(), DiscoveryRegistry())


async def test_real_tier2_tool_requires_preview(server, mock_client):
    import httpx
    import respx

    from unifi_mcp.tools.network.clients import block_client

    manager = SafetyManager()
    tool = server.build_tool_wrapper(block_client, client=mock_client, safety=manager)
    with respx.mock(assert_all_called=False) as router:
        route = router.post("https://192.168.1.1/proxy/network/api/s/default/cmd/stamgr").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        refused = await tool(mac="aa:bb:cc:00:00:01", confirm=True)
        assert refused["category"] == "PREVIEW_REQUIRED"
        assert route.call_count == 0

        preview = await tool(mac="aa:bb:cc:00:00:01")
        assert preview["preview"] is True
        assert route.call_count == 0

        done = await tool(mac="aa:bb:cc:00:00:01", confirm=True)
        assert done["executed"] is True
        assert route.call_count == 1

    log = manager.get_mutation_log()
    assert log[0]["tool"] == "block_client"
    assert log[0]["params"] == {"mac": "aa:bb:cc:00:00:01"}
    assert log[0]["result"] == {"action": "block_client", "executed": True}


def test_every_product_tool_wraps_cleanly(server):
    from unifi_mcp.tools._registry import load_product_tools

    for product in ("network", "protect"):
        for fn in load_product_tools(product):
            wrapped = server.build_tool_wrapper(fn, client=object(), safety=SafetyManager())
            params = inspect.signature(wrapped).parameters
            assert "client" not in params, fn.__name__
            assert wrapped.__name__ == fn.__name__


def test_returns_list_detection(server):
    async def a(client) -> list[dict]: ...
    async def b(client) -> dict: ...
    async def c(client): ...
    async def d(client) -> "list[dict]": ...
    async def e(client) -> list: ...
    d.__annotations__ = {"return": "list[Undefined]"}  # unresolvable string annotation

    assert server._returns_list(a) is True
    assert server._returns_list(b) is False
    assert server._returns_list(c) is False
    assert server._returns_list(d) is True
    assert server._returns_list(e) is True


def test_summarize_result_shapes(server):
    assert server._summarize_result([1, 2]) == {"type": "list"}
    assert server._summarize_result({"executed": True, "response": {"x_passphrase": "p"}}) == {
        "executed": True,
    }
    long = server._summarize_result({"error": True, "message": "x" * 1000})
    assert len(long["message"]) == 300
    assert server._summarize_result({"message": 5}) == {"message": 5}


async def test_never_previews_stub_returns_its_own_error_on_confirm(env):
    from unifi_mcp.server import build_tool_wrapper

    async def stub_tool(client, camera_id: str, confirm: bool = False) -> dict:
        return {"error": True, "category": "PRODUCT_UNAVAILABLE", "message": "no"}

    stub_tool.never_previews = True
    wrapped = build_tool_wrapper(stub_tool, client=object(), safety=env["safety"])
    result = await wrapped(camera_id="c1", confirm=True)
    assert result["category"] == "PRODUCT_UNAVAILABLE"
