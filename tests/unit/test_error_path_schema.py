"""Every list-returning tool must report input errors in a shape its output schema accepts."""

import pytest
from fastmcp import Client, FastMCP

from unifi_mcp.cloud_loader import bind_cloud_client
from unifi_mcp.tools.cloud import hosts, isp_metrics
from unifi_mcp.tools.network import hotspot, lookups

pytestmark = pytest.mark.asyncio

NETWORK_CASES = [
    (lookups.search_dpi_applications, {"query": ""}),
    (lookups.search_dpi_applications, {"query": "zoom", "limit": 0}),
    (hotspot.list_vouchers_v1, {"filter": "   "}),
]
CLOUD_CASES = [
    (hosts.list_cloud_devices, {"host_ids": []}),
    (isp_metrics.get_isp_metrics, {"metric_type": "1h", "duration": "24h"}),
]


async def _call(fn, args):
    app = FastMCP("schema-test")
    app.tool()(fn)
    async with Client(app) as c:
        return await c.call_tool(fn.__name__, args)


@pytest.mark.parametrize("fn,args", NETWORK_CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_network_error_path_passes_output_schema(server, fn, args):
    wrapped = server.build_tool_wrapper(fn, client=object(), safety=server.safety)
    result = await _call(wrapped, args)
    assert result.data["category"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("fn,args", CLOUD_CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_cloud_error_path_passes_output_schema(fn, args):
    result = await _call(bind_cloud_client(fn, object()), args)
    assert result.data["category"] == "VALIDATION_ERROR"


async def test_server_registers_cloud_loader(server):
    async with Client(server.mcp) as c:
        names = {t.name for t in await c.list_tools()}
    assert "load_cloud_tools" in names
