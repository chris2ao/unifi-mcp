"""Tool module auto-discovery, tool groups, tier merging, and load bookkeeping.

Every non-underscore module in `unifi_mcp.tools.<product>` is a tool module.
A module exports `TOOLS` (async tool functions), and from v0.6.0 also declares
`GROUP` (which product loader group it belongs to) and `TIER2_TOOLS`
(tool_name -> cache_category for every preview-confirm tool). Modules written
before v0.6.0 get their group from DEFAULT_GROUPS and their Tier 2 entries from
the legacy map in `unifi_mcp.safety`.

A module that fails to import is reported on stderr and skipped, so one broken
module never takes the whole loader down.
"""

import importlib
import pkgutil
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from unifi_mcp.safety import SafetyManager, legacy_tier2_for

TOOLS_PACKAGE = "unifi_mcp.tools"
PRODUCTS: tuple[str, ...] = ("network", "protect", "access")
ALL_GROUPS = "all"

# Groups for modules that predate the module-level GROUP declaration.
DEFAULT_GROUPS: dict[str, dict[str, str]] = {
    "network": {
        **dict.fromkeys(
            ("system", "devices", "clients", "networks", "wifi", "topology",
             "backups", "hotspot", "port_profiles"),
            "core",
        ),
        **dict.fromkeys(
            ("firewall", "zbf", "mac_acl", "radius", "port_forwarding",
             "traffic_rules", "qos", "vpn", "webhooks"),
            "security",
        ),
        **dict.fromkeys(("dpi", "traffic_flows"), "insights"),
    },
    "protect": {
        **dict.fromkeys(("cameras", "events", "recordings"), "cameras"),
        "devices": "devices",
    },
}

# Group for a module with no GROUP and no DEFAULT_GROUPS entry.
FALLBACK_GROUPS: dict[str, str] = {
    "network": "core",
    "protect": "cameras",
    "access": "core",
    "cloud": "cloud",
}
_DEFAULT_FALLBACK_GROUP = "core"

# Probe endpoints to detect installed products
PRODUCT_PROBES: dict[str, str] = {
    "network": "/proxy/network/api/s/{site}/stat/sysinfo",
    "protect": "/proxy/protect/integration/v1/meta/info",
    "access": "/proxy/access/api/v2/bootstrap",
}

_GROUP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_MAX_ERROR_TEXT = 300
_MAX_ECHOED_NAME = 40


@dataclass(frozen=True)
class ToolModule:
    """One discovered tool module and what it contributes."""

    product: str
    name: str
    group: str
    tools: tuple[Callable[..., Any], ...]
    tier2: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def key(self) -> str:
        return f"{self.product}.{self.name}"

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(fn.__name__ for fn in self.tools)


@dataclass(frozen=True)
class ModuleError:
    """A tool module that could not be imported."""

    product: str
    name: str
    error: str

    def to_dict(self) -> dict[str, str]:
        return {"product": self.product, "module": self.name, "error": self.error}


# --------------------------------------------------------------- discovery


def discover_module_names(product: str, *, package: str = TOOLS_PACKAGE) -> list[str]:
    """Sorted names of the tool modules in `<package>.<product>` (no "_" names)."""
    package_name = f"{package}.{product}"
    try:
        pkg = importlib.import_module(package_name)
    except Exception as exc:  # a broken package __init__ must not crash the loader
        missing = isinstance(exc, ModuleNotFoundError) and (
            exc.name == package_name or package_name.startswith(f"{exc.name}.")
        )
        if not missing:
            report_module_errors([ModuleError(product, "__init__", _error_text(exc))])
        return []
    paths = getattr(pkg, "__path__", None)
    if paths is None:
        return []
    return sorted(
        info.name for info in pkgutil.iter_modules(paths) if not info.name.startswith("_")
    )


def _module_group(product: str, name: str, module: Any) -> str:
    declared = getattr(module, "GROUP", None)
    if isinstance(declared, str) and _GROUP_NAME_RE.match(declared.strip().lower()):
        return declared.strip().lower()
    legacy = DEFAULT_GROUPS.get(product, {}).get(name)
    return legacy or FALLBACK_GROUPS.get(product, _DEFAULT_FALLBACK_GROUP)


def module_tier2_tools(product: str, name: str, module: Any) -> dict[str, str]:
    """Tier 2 entries for one module: its TIER2_TOOLS plus applicable legacy entries.

    Legacy entries only count for tools the module still exports, so a tool
    that moved to another module follows that module's declaration. A
    module-level declaration wins over a legacy entry for the same tool.
    """
    exported = {fn.__name__ for fn in getattr(module, "TOOLS", None) or []}
    legacy = {
        tool: category
        for tool, category in legacy_tier2_for(f"{product}.{name}").items()
        if tool in exported
    }
    declared = getattr(module, "TIER2_TOOLS", None) or {}
    if not isinstance(declared, Mapping):
        declared = {}
    valid = {
        tool: category for tool, category in declared.items()
        if isinstance(tool, str) and tool and isinstance(category, str) and category
    }
    if len(valid) != len(declared):
        print(
            f"unifi-mcp: ignored invalid TIER2_TOOLS entries in {TOOLS_PACKAGE}.{product}.{name} "
            "(need tool_name -> cache_category strings)",
            file=sys.stderr,
            flush=True,
        )
    return {**legacy, **valid}


def _build_module(product: str, name: str, module: Any) -> ToolModule:
    tools = tuple(fn for fn in (getattr(module, "TOOLS", None) or []) if callable(fn))
    return ToolModule(
        product=product,
        name=name,
        group=_module_group(product, name, module),
        tools=tools,
        tier2=MappingProxyType(module_tier2_tools(product, name, module)),
    )


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_TEXT]


def scan_tool_modules(
    product: str,
    *,
    package: str = TOOLS_PACKAGE,
    include: Callable[[str], bool] | None = None,
) -> tuple[list[ToolModule], list[ModuleError]]:
    """Import every tool module of a product, collecting failures instead of raising.

    `include(module_name)` can restrict which modules are imported at all.
    """
    modules: list[ToolModule] = []
    errors: list[ModuleError] = []
    for name in discover_module_names(product, package=package):
        if include is not None and not include(name):
            continue
        try:
            module = importlib.import_module(f"{package}.{product}.{name}")
        except Exception as exc:  # any import-time failure skips just this module
            errors = [*errors, ModuleError(product, name, _error_text(exc))]
            continue
        modules = [*modules, _build_module(product, name, module)]
    return modules, errors


def report_module_errors(errors: Iterable[ModuleError]) -> None:
    """Write one line per skipped module to stderr (stdout carries the MCP stream)."""
    for err in errors:
        print(
            f"unifi-mcp: skipped tool module {TOOLS_PACKAGE}.{err.product}.{err.name} "
            f"({err.error})",
            file=sys.stderr,
            flush=True,
        )


def discover_tool_modules(
    product: str, *, package: str = TOOLS_PACKAGE, strict: bool = False,
) -> list[ToolModule]:
    """Discovered, importable tool modules of a product, sorted by module name.

    Import failures are logged to stderr and skipped, or raised as ImportError
    when `strict` is True.
    """
    modules, errors = scan_tool_modules(product, package=package)
    if errors and strict:
        detail = "; ".join(f"{e.product}.{e.name}: {e.error}" for e in errors)
        raise ImportError(f"Tool modules failed to import: {detail}")
    report_module_errors(errors)
    return modules


def _compute_product_modules() -> dict[str, list[str]]:
    return {product: discover_module_names(product) for product in sorted(PRODUCTS)}


# Backward-compatible view: product -> sorted module names, discovered at import.
PRODUCT_MODULES: dict[str, list[str]] = _compute_product_modules()


# ------------------------------------------------------------ tools/groups


def _require_product(product: str) -> None:
    if product not in PRODUCTS:
        raise ValueError(f"Unknown product: {product}")


def available_groups(modules: Iterable[ToolModule]) -> list[str]:
    """Sorted group names present in a set of modules."""
    return sorted({m.group for m in modules})


def select_tools(
    modules: Iterable[ToolModule], groups: Iterable[str] | None = None,
) -> list[Callable[..., Any]]:
    """Tool functions of the modules in `groups` (all modules when None), first name wins."""
    wanted = None if groups is None else set(groups)
    seen: set[str] = set()
    selected: list[Callable[..., Any]] = []
    for module in modules:
        if wanted is not None and module.group not in wanted:
            continue
        for fn in module.tools:
            if fn.__name__ not in seen:
                seen = seen | {fn.__name__}
                selected = [*selected, fn]
    return selected


def load_product_tools(product: str, groups: Iterable[str] | None = None) -> list[Any]:
    """Import a product's tool modules and return their tools (optionally only some groups)."""
    _require_product(product)
    return select_tools(discover_tool_modules(product), groups)


def merge_module_tiers(manager: SafetyManager, modules: Iterable[ToolModule]) -> None:
    """Apply each module's Tier 2 declarations to a SafetyManager."""
    for module in modules:
        manager.apply_tool_tiers(module.tool_names, module.tier2)


def group_catalog(modules: Iterable[ToolModule]) -> dict[str, dict[str, Any]]:
    """group -> {"modules": [...], "tool_count": n} for a product's modules."""
    catalog: dict[str, dict[str, Any]] = {}
    for module in modules:
        entry = catalog.get(module.group, {"modules": [], "tool_count": 0})
        catalog = {
            **catalog,
            module.group: {
                "modules": [*entry["modules"], module.name],
                "tool_count": entry["tool_count"] + len(module.tools),
            },
        }
    return {group: catalog[group] for group in sorted(catalog)}


def _normalize_group(product: str, raw: Any) -> tuple[str | None, str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, f"Group names must be non-empty strings, got {repr(raw)[:_MAX_ECHOED_NAME]}."
    name = raw.strip().lower()
    prefix, sep, rest = name.partition(":")
    if sep:
        if prefix != product:
            return None, (
                f"Group '{raw[:_MAX_ECHOED_NAME]}' is for product "
                f"'{prefix[:_MAX_ECHOED_NAME]}', not {product}."
            )
        name = rest.strip()
    return name, None


def resolve_groups(
    product: str,
    requested: Sequence[str] | None,
    available: Iterable[str],
    *,
    source: str = "groups",
) -> tuple[frozenset[str], str | None]:
    """Turn requested group names into a set of known groups, or an error message.

    None or an empty list selects every available group, as does "all".
    Names may carry the product prefix ("network:core").
    """
    known = frozenset(available)
    if not requested:
        return known, None
    if isinstance(requested, str):
        requested = [requested]
    names: list[str] = []
    for raw in requested:
        name, error = _normalize_group(product, raw)
        if error:
            return frozenset(), f"Invalid {source}: {error}"
        names = [*names, name]
    if ALL_GROUPS in names:
        return known, None
    unknown = sorted({name[:_MAX_ECHOED_NAME] for name in names} - known)
    if unknown:
        return frozenset(), (
            f"Unknown {product} tool group(s) in {source}: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(known)) or 'none'}. "
            "Call list_tool_groups for details."
        )
    return frozenset(names), None


# ------------------------------------------------------------- bookkeeping


class ProductRegistry:
    """Tracks which products, groups and tool names have been registered."""

    def __init__(self) -> None:
        self._loaded: dict[str, int] = {}
        self._groups: dict[str, frozenset[str]] = {}
        self._registered: frozenset[str] = frozenset()

    @property
    def products(self) -> dict[str, list[str]]:
        """A copy of PRODUCT_MODULES (product -> sorted module names)."""
        return {product: list(names) for product, names in PRODUCT_MODULES.items()}

    @property
    def registered_tools(self) -> frozenset[str]:
        return self._registered

    def is_loaded(self, product: str) -> bool:
        return product in self._loaded

    def is_registered(self, tool_name: str) -> bool:
        return tool_name in self._registered

    def loaded_groups(self, product: str) -> frozenset[str]:
        return self._groups.get(product, frozenset())

    def mark_loaded(self, product: str, tool_count: int) -> None:
        """Mark a product loaded with an absolute tool count (pre-v0.6.0 API)."""
        self._loaded = {**self._loaded, product: tool_count}

    def record_load(
        self, product: str, groups: Iterable[str], new_tool_names: Iterable[str],
    ) -> None:
        """Record a (possibly incremental) load: groups now loaded and newly registered tools."""
        fresh = [n for n in dict.fromkeys(new_tool_names) if n not in self._registered]
        self._registered = self._registered | frozenset(fresh)
        self._loaded = {**self._loaded, product: self._loaded.get(product, 0) + len(fresh)}
        self._groups = {**self._groups, product: self.loaded_groups(product) | set(groups)}

    def get_summary(self) -> dict:
        return {
            product: {
                "loaded": product in self._loaded,
                "tool_count": self._loaded.get(product, 0),
                "groups": sorted(self.loaded_groups(product)),
            }
            for product in PRODUCT_MODULES
        }

    def group_report(self, products: Iterable[str] = PRODUCTS) -> dict[str, Any]:
        """Per product: every group with its modules, tool count and loaded flag."""
        report: dict[str, Any] = {}
        skipped: list[dict[str, str]] = []
        for product in products:
            modules, errors = scan_tool_modules(product)
            loaded = self.loaded_groups(product)
            report = {**report, product: [
                {"group": group, **info, "loaded": group in loaded}
                for group, info in group_catalog(modules).items()
            ]}
            skipped = [*skipped, *(e.to_dict() for e in errors)]
        return {"products": report, "skipped_modules": skipped}
