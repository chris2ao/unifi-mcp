import functools
import inspect

from fastmcp import Context, FastMCP

from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.safety import SafetyManager
from unifi_mcp.tools._registry import ProductRegistry, load_product_tools, PRODUCT_PROBES
from unifi_mcp.errors import UnifiError

mcp = FastMCP("chris2ao-unifi-mcp")

# Initialized at module load from env vars
config = UnifiConfig()
cache = TTLCache()
discovery = DiscoveryRegistry()
client = UnifiClient(config, cache, discovery)
safety = SafetyManager()
registry = ProductRegistry()


def _bind_client(tool_fn):
    """Return a wrapper with `client` pre-bound and removed from the public signature.

    FastMCP builds a JSON schema from the callable's signature. The UnifiClient
    type is not JSON-serializable, so every tool parameter list starts with an
    infrastructure-only `client` argument that must be hidden from the schema.
    """
    original_sig = inspect.signature(tool_fn)
    public_params = [
        p for name, p in original_sig.parameters.items() if name != "client"
    ]
    public_sig = original_sig.replace(parameters=public_params)

    @functools.wraps(tool_fn)
    async def wrapper(*args, **kwargs):
        return await tool_fn(client, *args, **kwargs)

    wrapper.__signature__ = public_sig
    wrapper.__annotations__ = {
        name: ann for name, ann in tool_fn.__annotations__.items() if name != "client"
    }
    return wrapper


async def _probe_product(product: str) -> bool:
    """Check if a UniFi product is installed on the console.

    A probe succeeds only when the endpoint returns a JSON body. UniFi OS falls
    back to an HTML landing page with HTTP 200 for uninstalled products, so the
    JSON check is required to avoid false positives (seen with Access).
    """
    probe_path = PRODUCT_PROBES.get(product)
    if not probe_path:
        return False
    try:
        result = await client.get(probe_path)
    except UnifiError:
        return False
    return isinstance(result, (dict, list))


async def _load_product(product: str, ctx: Context | None = None) -> str:
    """Load tools for a product and register them with FastMCP."""
    if registry.is_loaded(product):
        return f"{product.title()} tools already loaded."

    if not await _probe_product(product):
        return f"UniFi {product.title()} is not installed on this console."

    tools = load_product_tools(product)
    for tool_fn in tools:
        mcp.tool()(_bind_client(tool_fn))

    registry.mark_loaded(product, len(tools))

    # FastMCP registers tools on the server but does not emit the MCP
    # notifications/tools/list_changed notification, so the client keeps its
    # stale tool list. Send it explicitly so the newly registered tools
    # become callable in the current session.
    if ctx is not None:
        await ctx.session.send_tool_list_changed()

    return f"Registered {len(tools)} {product} tools."


@mcp.tool()
async def load_network_tools(ctx: Context) -> str:
    """Load all UniFi Network management tools (devices, clients, firewall, WiFi, VPN, topology, and more)."""
    return await _load_product("network", ctx)


@mcp.tool()
async def load_protect_tools(ctx: Context) -> str:
    """Load UniFi Protect tools (cameras, motion events, recordings, smart detection)."""
    return await _load_product("protect", ctx)


@mcp.tool()
async def load_access_tools(ctx: Context) -> str:
    """Load UniFi Access tools (door control, NFC/PIN credentials, visitor passes, access policies)."""
    return await _load_product("access", ctx)


@mcp.tool()
async def get_auth_report() -> dict:
    """Get the auth discovery report showing API key success/failure per endpoint tested."""
    return {
        "summary": discovery.get_summary(),
        "auth_failures": discovery.get_auth_failures(),
        "full_log": discovery.get_report(),
    }


@mcp.tool()
async def get_server_info() -> dict:
    """Get server status including loaded products and tool counts."""
    return {
        "server": "chris2ao-unifi-mcp",
        "version": "0.2.1",
        "console": config.unifi_host,
        "site": config.unifi_site,
        "products": registry.get_summary(),
    }


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
