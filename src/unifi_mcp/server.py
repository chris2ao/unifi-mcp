import asyncio
import functools
import inspect
import logging
import re
import typing
import unicodedata
from collections.abc import Callable
from typing import Any

from fastmcp import Context, FastMCP

from unifi_mcp import __version__
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry
from unifi_mcp.safety import SafetyManager
from unifi_mcp.tools._registry import (
    PRODUCT_PROBES,
    ProductRegistry,
    available_groups,
    discover_tool_modules,
    merge_module_tiers,
    resolve_groups,
    select_tools,
)
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import validation_error

logger = logging.getLogger(__name__)

mcp = FastMCP("chris2ao-unifi-mcp")

# Initialized at module load from env vars
config = UnifiConfig()
cache = TTLCache()
discovery = DiscoveryRegistry()
client = UnifiClient(config, cache, discovery)
safety = SafetyManager(preview_ttl_seconds=config.unifi_preview_ttl_seconds)
registry = ProductRegistry()

# Values that would change the meaning of a URL path if interpolated into it.
_PATH_ARG_TOKENS = ("/", "\\", "..", "?", "#", "%")
_RESULT_SUMMARY_KEYS = ("action", "executed", "error", "category", "message")
_MAX_LOGGED_MESSAGE = 300

# Console application versions this server's tools were last verified against.
# get_server_info reports drift when the console's major.minor differs.
VERIFIED_VERSIONS: dict[str, str] = {"network": "10.6.106", "protect": "7.2.105"}
_VERSION_ENDPOINTS: dict[str, str] = {
    "network": "/proxy/network/integration/v1/info",
    "protect": "/proxy/protect/integration/v1/meta/info",
}
_VERSION_CACHE_CATEGORY = "server_info"
_VERSION_CACHE_TTL = 60.0
_VERSION_TIMEOUT = 5.0
_MAJOR_MINOR_RE = re.compile(r"^\D*(\d+)\.(\d+)")

# Serializes loader calls so concurrent calls never register a tool twice.
_load_lock = asyncio.Lock()


def _is_path_param(name: str) -> bool:
    """Parameters that tools interpolate into URL paths (ids and MACs)."""
    return name in ("id", "mac") or name.endswith("_id") or name.endswith("_mac")


def _is_unsafe_path_value(value: str) -> bool:
    if any(token in value for token in _PATH_ARG_TOKENS):
        return True
    return any(ch.isspace() or unicodedata.category(ch) == "Cc" for ch in value)


def _path_arg_error(arguments: dict[str, Any]) -> dict | None:
    """Reject id/mac string args that could escape their URL path segment."""
    for name, value in arguments.items():
        if isinstance(value, str) and _is_path_param(name) and _is_unsafe_path_value(value):
            return validation_error(
                f"{name} must be a plain identifier: '/', '\\', '..', '?', '#', '%', "
                "whitespace and control characters are not allowed."
            )
    return None


def _returns_list(tool_fn: Callable) -> bool:
    """True when the tool is annotated to return a list (errors must match that shape)."""
    try:
        hint = typing.get_type_hints(tool_fn).get("return")
    except Exception:
        hint = getattr(tool_fn, "__annotations__", {}).get("return")
    if isinstance(hint, str):
        return hint.strip().startswith("list")
    return hint is list or typing.get_origin(hint) is list


def _preview_required(tool_name: str) -> dict:
    return {
        "error": True,
        "category": str(ErrorCategory.PREVIEW_REQUIRED),
        "message": (
            f"Call {tool_name} with confirm=False and the same parameters, review "
            "the preview, then call again with confirm=True."
        ),
    }


def _summarize_result(result: Any) -> dict:
    """Keep only status fields for the audit log (full responses may hold secrets)."""
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    summary = {k: result[k] for k in _RESULT_SUMMARY_KEYS if k in result}
    message = summary.get("message")
    if isinstance(message, str):
        return {**summary, "message": message[:_MAX_LOGGED_MESSAGE]}
    return summary


async def _run_guarded(
    tool_fn: Callable, tool_name: str, tool_client: Any, manager: SafetyManager,
    bound: inspect.BoundArguments, params: dict[str, Any],
) -> Any:
    """Enforce preview-then-confirm for a Tier 2 tool call."""
    if not bound.arguments.get("confirm"):
        result = await tool_fn(tool_client, *bound.args, **bound.kwargs)
        if isinstance(result, dict) and result.get("preview") is True:
            manager.record_preview(tool_name, params)
        return result

    # Single use: the preview is consumed before execution, even if it fails.
    if getattr(tool_fn, "never_previews", False):
        # Stub that can never produce a preview: run it so the caller gets its
        # real PRODUCT_UNAVAILABLE explanation instead of a preview/confirm loop.
        return await tool_fn(tool_client, *bound.args, **bound.kwargs)
    if not manager.consume_preview(tool_name, params):
        return _preview_required(tool_name)
    try:
        result = await tool_fn(tool_client, *bound.args, **bound.kwargs)
    except Exception as exc:
        manager.log_mutation(tool_name, params, {
            "error": True,
            "exception": type(exc).__name__,
            "message": str(exc)[:_MAX_LOGGED_MESSAGE],
        })
        raise
    manager.log_mutation(tool_name, params, _summarize_result(result))
    return result


def build_tool_wrapper(tool_fn: Callable, *, client: Any, safety: SafetyManager) -> Callable:
    """Wrap a tool for registration: bind `client`, validate path args, enforce preview-confirm.

    FastMCP builds a JSON schema from the callable's signature. The UnifiClient
    type is not JSON-serializable, so the infrastructure-only `client`
    argument is removed from the public signature.

    Any tool whose signature has a `confirm` parameter is guarded: a
    confirm=True call only runs when a preview (confirm=False returning
    {"preview": True}) with identical parameters was recorded within the
    configured TTL. Previews are single use and confirmed calls are audited.
    """
    original_sig = inspect.signature(tool_fn)
    public_params = [
        p for name, p in original_sig.parameters.items() if name != "client"
    ]
    public_sig = original_sig.replace(parameters=public_params)
    tool_name = tool_fn.__name__
    guarded = "confirm" in public_sig.parameters
    list_shaped = _returns_list(tool_fn)

    def _shape(error: dict) -> Any:
        return [error] if list_shaped else error

    @functools.wraps(tool_fn)
    async def wrapper(*args, **kwargs):
        try:
            bound = public_sig.bind(*args, **kwargs)
        except TypeError as exc:
            return _shape(validation_error(f"Invalid arguments for {tool_name}: {exc}"))
        bound.apply_defaults()
        rejection = _path_arg_error(bound.arguments)
        if rejection:
            return _shape(rejection)
        if not guarded:
            return await tool_fn(client, *bound.args, **bound.kwargs)
        params = {k: v for k, v in bound.arguments.items() if k != "confirm"}
        return await _run_guarded(tool_fn, tool_name, client, safety, bound, params)

    wrapper.__signature__ = public_sig
    wrapper.__annotations__ = {
        name: ann for name, ann in tool_fn.__annotations__.items() if name != "client"
    }
    return wrapper


def _bind_client(tool_fn):
    """Return the registration wrapper bound to this server's client and safety manager."""
    return build_tool_wrapper(tool_fn, client=client, safety=safety)


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


def _loaded_groups_line(product: str, catalog: list[str]) -> str:
    loaded = sorted(registry.loaded_groups(product))
    pending = [g for g in catalog if g not in loaded]
    line = f"Loaded {product} groups: {', '.join(loaded) or 'none'}"
    if pending:
        line += f"; not loaded: {', '.join(pending)} (call again with groups=[...] to add)"
    return line + "."


async def _register_groups(product: str, groups: list[str] | None, ctx: Context | None) -> str:
    modules = discover_tool_modules(product)
    catalog = available_groups(modules)
    from_env = not groups
    requested = groups or config.tool_groups_for(product)
    source = "UNIFI_TOOL_GROUPS" if from_env and requested else "groups"
    selected, error = resolve_groups(product, requested, catalog, source=source)
    if error:
        return error

    if not registry.is_loaded(product) and not await _probe_product(product):
        return f"UniFi {product.title()} is not installed on this console."
    if registry.is_loaded(product) and selected <= registry.loaded_groups(product):
        names = ", ".join(sorted(selected)) or "none"
        return f"{product.title()} tools already loaded (groups: {names})."

    merge_module_tiers(safety, modules)
    new_tools = [
        fn for fn in select_tools(modules, selected) if not registry.is_registered(fn.__name__)
    ]
    for tool_fn in new_tools:
        mcp.tool()(_bind_client(tool_fn))
    registry.record_load(product, selected, [fn.__name__ for fn in new_tools])

    # FastMCP registers tools on the server but does not emit the MCP
    # notifications/tools/list_changed notification, so the client keeps its
    # stale tool list. Send it explicitly so the newly registered tools
    # become callable in the current session.
    if ctx is not None and new_tools:
        await ctx.session.send_tool_list_changed()

    groups_text = ", ".join(sorted(selected)) or "none"
    return (
        f"Registered {len(new_tools)} {product} tools (groups: {groups_text}). "
        + _loaded_groups_line(product, catalog)
    )


async def _load_product(
    product: str, ctx: Context | None = None, groups: list[str] | None = None,
) -> str:
    """Register a product's tools for the requested groups (default: UNIFI_TOOL_GROUPS or all).

    Loading is incremental: a later call with more groups registers only the
    tools that are not registered yet.
    """
    async with _load_lock:
        return await _register_groups(product, groups, ctx)


@mcp.tool()
async def load_network_tools(ctx: Context, groups: list[str] | None = None) -> str:
    """Load UniFi Network tools, optionally only some groups: core, security, insights.

    core: system, devices, clients, networks, WiFi, topology, backups, hotspot,
    port profiles. security: firewall, zone-based firewall, MAC ACL, RADIUS,
    port forwarding, traffic rules, QoS, VPN, DNS policies. insights: DPI,
    traffic flows, routing, dashboards and other read-only reports.
    groups: e.g. ["core", "security"]; omit to use UNIFI_TOOL_GROUPS or load
    every group. Call again with more groups to add them (only new tools are
    registered). list_tool_groups shows the current groups and tool counts.
    """
    return await _load_product("network", ctx, groups)


@mcp.tool()
async def load_protect_tools(ctx: Context, groups: list[str] | None = None) -> str:
    """Load UniFi Protect tools, optionally only some groups: cameras, devices, security.

    cameras: cameras, events, live views. devices: NVRs and accessories.
    security: Alarm Manager. groups: e.g. ["cameras"]; omit to use
    UNIFI_TOOL_GROUPS or load every group. Call again with more groups to add
    them (only new tools are registered). list_tool_groups shows the current
    groups and tool counts.
    """
    return await _load_product("protect", ctx, groups)


@mcp.tool()
async def load_access_tools(ctx: Context) -> str:
    """Load UniFi Access tools (door control, NFC/PIN credentials, visitor passes, access policies)."""
    return await _load_product("access", ctx)


@mcp.tool()
async def list_tool_groups() -> dict:
    """List the tool groups each product loader can register: group name, modules, tool count, and whether it is loaded.

    Use it to pick groups for load_network_tools(groups=[...]) or
    load_protect_tools(groups=[...]) and keep the tool list small. Does not
    contact the console.
    """
    report = registry.group_report()
    return {
        **report,
        "default_groups": config.unifi_tool_groups or "all",
        "usage": (
            "Pass group names to a loader, e.g. load_network_tools(groups=[\"core\"]). "
            "Calling a loader again with more groups adds only the new tools. "
            "UNIFI_TOOL_GROUPS (e.g. network:core,protect:cameras) sets the default."
        ),
    }


@mcp.tool()
async def get_auth_report() -> dict:
    """Get the auth discovery report showing API key success/failure per endpoint tested."""
    return {
        "summary": discovery.get_summary(),
        "auth_failures": discovery.get_auth_failures(),
        "full_log": discovery.get_report(),
    }


def _major_minor(version: str | None) -> tuple[int, int] | None:
    match = _MAJOR_MINOR_RE.match(version or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def firmware_drift(
    console_versions: dict[str, str | None],
    verified: dict[str, str] = VERIFIED_VERSIONS,
) -> list[str]:
    """Products whose console major.minor differs from the verified version (unknown is not drift)."""
    drifted = []
    for product, verified_version in verified.items():
        actual = _major_minor(console_versions.get(product))
        if actual is not None and actual != _major_minor(verified_version):
            drifted = [*drifted, product]
    return sorted(drifted)


async def _fetch_version(api_client: Any, product: str, path: str) -> str | None:
    """Best-effort application version lookup; never raises."""
    try:
        result = await asyncio.wait_for(
            api_client.get(path, cache_category=_VERSION_CACHE_CATEGORY,
                           cache_ttl=_VERSION_CACHE_TTL),
            timeout=_VERSION_TIMEOUT,
        )
    except UnifiError as exc:
        logger.info("%s version lookup failed: %s", product, exc.category)
        return None
    except Exception as exc:  # best effort: get_server_info must always answer
        logger.warning("%s version lookup failed: %s", product, type(exc).__name__)
        return None
    version = result.get("applicationVersion") if isinstance(result, dict) else None
    return version.strip() if isinstance(version, str) and version.strip() else None


async def console_versions(api_client: Any) -> dict[str, str | None]:
    """Network and Protect application versions reported by the console (None if unknown)."""
    products = list(_VERSION_ENDPOINTS)
    versions = await asyncio.gather(
        *(_fetch_version(api_client, p, _VERSION_ENDPOINTS[p]) for p in products)
    )
    return dict(zip(products, versions))


def _drift_hint(drift: list[str], versions: dict[str, str | None]) -> str | None:
    if not drift:
        return None
    details = ", ".join(
        f"{p} {versions.get(p)} (verified {VERIFIED_VERSIONS[p]})" for p in drift
    )
    return (
        f"Console firmware differs from the verified versions: {details}. Some tools "
        "may behave differently. Run scripts/spec_diff.py to list API changes."
    )


@mcp.tool()
async def get_server_info() -> dict:
    """Get server status: package version, console, site, preview TTL, loaded products and groups, and console firmware drift.

    console_versions are the Network and Protect versions the console reports
    (null when unknown); verified_versions are the versions this server was
    tested against; drift lists products whose major.minor differs.
    """
    versions = await console_versions(client)
    drift = firmware_drift(versions)
    return {
        "server": "chris2ao-unifi-mcp",
        "version": __version__,
        "console": config.unifi_host,
        "site": config.unifi_site,
        "preview_ttl_seconds": config.unifi_preview_ttl_seconds,
        "products": registry.get_summary(),
        "console_versions": versions,
        "verified_versions": dict(VERIFIED_VERSIONS),
        "drift": drift,
        "drift_hint": _drift_hint(drift, versions),
    }


@mcp.tool()
async def get_mutation_log() -> list[dict]:
    """Get the audit log of confirmed Tier 2 (preview-confirm) changes made in this server session, oldest first.

    Each entry has tool, params, a result summary and a UTC timestamp.
    Secret-looking params (keys containing pass, secret, key, token or psk,
    or starting with x_) are masked as "***". The log is in memory only and
    resets when the server restarts.
    """
    return safety.get_mutation_log()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
