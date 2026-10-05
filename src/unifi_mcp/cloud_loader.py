"""On-demand loader for the optional Site Manager (cloud) tool set."""

import functools
import inspect
import logging
from typing import Any, Callable

from fastmcp import Context
from pydantic import ValidationError

from unifi_mcp.cloud.client import CloudClient
from unifi_mcp.cloud.config import CloudConfig

logger = logging.getLogger(__name__)

NO_KEY_MESSAGE = (
    "UNIFI_CLOUD_API_KEY is not set. Create a cloud API key at unifi.ui.com "
    "(Settings, API), set UNIFI_CLOUD_API_KEY in the MCP server environment "
    "(this is separate from UNIFI_API_KEY), restart the server, then call "
    "load_cloud_tools again."
)


def bind_cloud_client(tool_fn: Callable, client: Any) -> Callable:
    """Bind `client` into a tool and hide it from the public signature (see server._bind_client)."""
    original_sig = inspect.signature(tool_fn)
    public = [p for name, p in original_sig.parameters.items() if name != "client"]

    @functools.wraps(tool_fn)
    async def wrapper(*args, **kwargs):
        return await tool_fn(client, *args, **kwargs)

    wrapper.__signature__ = original_sig.replace(parameters=public)
    wrapper.__annotations__ = {
        k: v for k, v in tool_fn.__annotations__.items() if k != "client"
    }
    return wrapper


def register_cloud_loader(mcp: Any, bind: Callable | None = None) -> None:
    """Register the `load_cloud_tools` MCP tool on `mcp`.

    `bind(tool_fn, client)` may be supplied to customize binding; the default
    hides the first `client` parameter from the tool schema.
    """
    binder = bind or bind_cloud_client
    state: dict[str, Any] = {"count": 0, "client": None}

    @mcp.tool()
    async def load_cloud_tools(ctx: Context) -> str:
        """Load UniFi Site Manager cloud tools (cloud hosts, sites, devices, ISP metrics history, SD-WAN). Requires UNIFI_CLOUD_API_KEY."""
        if state["client"] is not None:
            return f"Cloud tools already loaded ({state['count']} tools)."
        try:
            config = CloudConfig()
        except ValidationError as exc:
            first = exc.errors()[0].get("msg", "invalid value")
            return f"Invalid cloud configuration: {first}"
        if not config.has_key:
            return NO_KEY_MESSAGE
        from unifi_mcp.tools.cloud import all_cloud_tools

        client = CloudClient(config)
        tools = all_cloud_tools()
        for tool_fn in tools:
            mcp.tool()(binder(tool_fn, client))
        state["client"], state["count"] = client, len(tools)
        if ctx is not None:
            await ctx.session.send_tool_list_changed()
        return f"Registered {len(tools)} cloud tools."
