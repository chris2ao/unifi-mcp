import inspect
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastmcp import FastMCP

from unifi_mcp.cloud_loader import NO_KEY_MESSAGE, bind_cloud_client, register_cloud_loader


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def make_ctx():
    ctx = MagicMock()
    ctx.session.send_tool_list_changed = AsyncMock()
    return ctx


def test_bind_hides_client():
    async def tool(client, a: int, b: str = "x") -> dict:
        return {"client": client, "a": a, "b": b}

    bound = bind_cloud_client(tool, "C")
    assert list(inspect.signature(bound).parameters) == ["a", "b"]
    assert "client" not in bound.__annotations__


async def test_bound_call_passes_client():
    async def tool(client, a): return (client, a)
    assert await bind_cloud_client(tool, "C")(1) == ("C", 1)


async def test_no_key_message(monkeypatch):
    monkeypatch.delenv("UNIFI_CLOUD_API_KEY", raising=False)
    mcp = FakeMCP()
    register_cloud_loader(mcp)
    ctx = make_ctx()
    assert await mcp.tools["load_cloud_tools"](ctx) == NO_KEY_MESSAGE
    assert set(mcp.tools) == {"load_cloud_tools"}
    ctx.session.send_tool_list_changed.assert_not_called()


async def test_invalid_base_url(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "k")
    monkeypatch.setenv("UNIFI_CLOUD_BASE_URL", "https://evil.example.com")
    mcp = FakeMCP()
    register_cloud_loader(mcp)
    msg = await mcp.tools["load_cloud_tools"](make_ctx())
    assert msg.startswith("Invalid cloud configuration")
    assert len(mcp.tools) == 1


async def test_loads_tools_once(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "k")
    monkeypatch.delenv("UNIFI_CLOUD_BASE_URL", raising=False)
    mcp = FakeMCP()
    register_cloud_loader(mcp)
    ctx = make_ctx()
    assert await mcp.tools["load_cloud_tools"](ctx) == "Registered 9 cloud tools."
    ctx.session.send_tool_list_changed.assert_awaited_once()
    assert "list_cloud_hosts" in mcp.tools and "query_isp_metrics" in mcp.tools
    assert "already loaded" in await mcp.tools["load_cloud_tools"](ctx)
    assert ctx.session.send_tool_list_changed.await_count == 1


@respx.mock
async def test_loaded_tool_calls_cloud_api(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "k")
    mcp = FakeMCP()
    register_cloud_loader(mcp)
    await mcp.tools["load_cloud_tools"](make_ctx())
    respx.get("https://api.ui.com/v1/sd-wan-configs").mock(return_value=httpx.Response(200, json={"data": [{"id": "1"}]}))
    assert await mcp.tools["list_sdwan_configs"]() == [{"id": "1"}]


async def test_custom_binder_and_none_ctx(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "k")
    mcp = FakeMCP()
    seen = []
    register_cloud_loader(mcp, bind=lambda fn, c: seen.append(fn) or fn)
    assert "Registered" in await mcp.tools["load_cloud_tools"](None)
    assert len(seen) == 9


async def test_real_fastmcp_schema_hides_client(monkeypatch):
    monkeypatch.setenv("UNIFI_CLOUD_API_KEY", "k")
    mcp = FastMCP("t")
    register_cloud_loader(mcp)
    loader = await mcp.get_tool("load_cloud_tools")
    await loader.fn(make_ctx())
    tool = await mcp.get_tool("get_cloud_host")
    props = tool.parameters["properties"]
    assert "host_id" in props and "client" not in props
