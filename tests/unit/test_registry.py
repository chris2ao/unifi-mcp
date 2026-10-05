"""Tests for tool module auto-discovery, groups, tier merging and load bookkeeping."""
import inspect
import sys
import textwrap
import uuid

import pytest

from unifi_mcp.safety import SafetyManager, SafetyTier
from unifi_mcp.tools import _registry
from unifi_mcp.tools._registry import (
    DEFAULT_GROUPS,
    PRODUCT_MODULES,
    PRODUCTS,
    ProductRegistry,
    ToolModule,
    available_groups,
    discover_module_names,
    discover_tool_modules,
    group_catalog,
    load_product_tools,
    merge_module_tiers,
    module_tier2_tools,
    resolve_groups,
    scan_tool_modules,
    select_tools,
)

GOOD_MODULE = '''
GROUP = "Reports"
TIER2_TOOLS = {"wipe_report": "reports"}

async def get_report(client) -> dict:
    """Get a report."""
    return {}

async def wipe_report(client, report_id: str, confirm: bool = False) -> dict:
    """Wipe a report."""
    return {}

TOOLS = [get_report, wipe_report]
'''

LEGACY_FIREWALL_MODULE = '''
async def list_firewall_rules(client) -> list[dict]:
    """List rules."""
    return []

async def create_firewall_rule(client, name: str, confirm: bool = False) -> dict:
    """Create a rule."""
    return {}

TOOLS = [list_firewall_rules, create_firewall_rule]
'''

UNMAPPED_MODULE = '''
async def odd_tool(client) -> dict:
    """Odd tool."""
    return {}

TOOLS = [odd_tool]
'''


@pytest.fixture
def fake_package(tmp_path, monkeypatch):
    """Build a throwaway tools package: <pkg>.network with good, legacy, broken and private modules."""
    name = f"fake_tools_{uuid.uuid4().hex[:12]}"
    root = tmp_path / name
    network = root / "network"
    network.mkdir(parents=True)
    (root / "__init__.py").write_text("")
    (network / "__init__.py").write_text("")
    (network / "reports.py").write_text(textwrap.dedent(GOOD_MODULE))
    (network / "firewall.py").write_text(textwrap.dedent(LEGACY_FIREWALL_MODULE))
    (network / "oddities.py").write_text(textwrap.dedent(UNMAPPED_MODULE))
    (network / "broken.py").write_text("import does_not_exist_anywhere_xyz\n")
    (network / "_helpers.py").write_text("TOOLS = ['not a tool module']\n")
    protect = root / "protect"
    protect.mkdir()
    (protect / "__init__.py").write_text("")
    (protect / "gadgets.py").write_text(textwrap.dedent(UNMAPPED_MODULE))
    monkeypatch.syspath_prepend(str(tmp_path))
    yield name
    for mod in [m for m in sys.modules if m == name or m.startswith(f"{name}.")]:
        sys.modules.pop(mod, None)


# --- discovery ---

def test_product_modules_is_sorted_and_covers_products():
    assert list(PRODUCT_MODULES) == sorted(PRODUCTS)
    for product, modules in PRODUCT_MODULES.items():
        assert modules == sorted(modules), product
        assert not [m for m in modules if m.startswith("_")]


def test_product_modules_matches_discovery():
    for product in PRODUCTS:
        assert PRODUCT_MODULES[product] == discover_module_names(product)


def test_network_has_expected_modules():
    modules = ProductRegistry().products["network"]
    for name in ("system", "devices", "clients", "firewall", "zbf", "topology", "traffic_flows"):
        assert name in modules


def test_registry_knows_product_modules():
    products = ProductRegistry().products
    assert {"network", "protect", "access"} <= set(products)


def test_discover_module_names_skips_private(fake_package):
    names = discover_module_names("network", package=fake_package)
    assert names == ["broken", "firewall", "oddities", "reports"]


def test_discover_module_names_missing_product_is_empty(fake_package, capsys):
    assert discover_module_names("access", package=fake_package) == []
    assert capsys.readouterr().err == ""


def test_discover_module_names_reports_broken_package_init(tmp_path, monkeypatch, capsys):
    name = f"fake_tools_{uuid.uuid4().hex[:12]}"
    (tmp_path / name / "network").mkdir(parents=True)
    (tmp_path / name / "__init__.py").write_text("")
    (tmp_path / name / "network" / "__init__.py").write_text("raise RuntimeError('boom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert discover_module_names("network", package=name) == []
    assert "RuntimeError: boom" in capsys.readouterr().err


def test_import_error_is_logged_to_stderr_and_skipped(fake_package, capsys):
    modules = discover_tool_modules("network", package=fake_package)
    assert [m.name for m in modules] == ["firewall", "oddities", "reports"]
    err = capsys.readouterr().err
    assert f"{_registry.TOOLS_PACKAGE}.network.broken" in err
    assert "ModuleNotFoundError" in err


def test_strict_discovery_raises(fake_package):
    with pytest.raises(ImportError, match="broken"):
        discover_tool_modules("network", package=fake_package, strict=True)


def test_scan_returns_errors_without_printing(fake_package, capsys):
    modules, errors = scan_tool_modules("network", package=fake_package)
    assert len(modules) == 3
    assert [e.name for e in errors] == ["broken"]
    assert errors[0].to_dict()["module"] == "broken"
    assert capsys.readouterr().err == ""


def test_scan_include_filter_skips_import(fake_package):
    modules, errors = scan_tool_modules(
        "network", package=fake_package, include=lambda name: name == "reports",
    )
    assert [m.name for m in modules] == ["reports"]
    assert errors == []


# --- groups ---

def test_module_group_declared_is_normalized(fake_package):
    modules = {m.name: m for m in discover_tool_modules("network", package=fake_package)}
    assert modules["reports"].group == "reports"


def test_module_group_from_default_map(fake_package):
    modules = {m.name: m for m in discover_tool_modules("network", package=fake_package)}
    assert modules["firewall"].group == "security"


def test_module_group_fallbacks(fake_package):
    network = {m.name: m for m in discover_tool_modules("network", package=fake_package)}
    protect = {m.name: m for m in discover_tool_modules("protect", package=fake_package)}
    assert network["oddities"].group == "core"
    assert protect["gadgets"].group == "cameras"


def test_invalid_declared_group_falls_back():
    class Mod:
        GROUP = "Not A Group!"
        TOOLS = []

    assert _registry._module_group("network", "zbf", Mod) == "security"
    assert _registry._module_group("unknown_product", "x", Mod) == "core"


def test_default_groups_cover_legacy_modules():
    network = DEFAULT_GROUPS["network"]
    assert {k for k, v in network.items() if v == "core"} == {
        "system", "devices", "clients", "networks", "wifi", "topology",
        "backups", "hotspot", "port_profiles",
    }
    assert {k for k, v in network.items() if v == "security"} == {
        "firewall", "zbf", "mac_acl", "radius", "port_forwarding",
        "traffic_rules", "qos", "vpn", "webhooks",
    }
    assert {k for k, v in network.items() if v == "insights"} == {"dpi", "traffic_flows"}
    assert DEFAULT_GROUPS["protect"] == {
        "cameras": "cameras", "events": "cameras", "recordings": "cameras",
        "devices": "devices",
    }


def test_real_network_modules_get_expected_groups():
    groups = {m.name: m.group for m in discover_tool_modules("network")}
    assert groups["system"] == "core"
    assert groups["firewall"] == "security"
    assert groups["traffic_flows"] == "insights"


def test_group_catalog_and_available_groups(fake_package):
    modules = discover_tool_modules("network", package=fake_package)
    catalog = group_catalog(modules)
    assert list(catalog) == ["core", "reports", "security"]
    assert catalog["security"] == {"modules": ["firewall"], "tool_count": 2}
    assert catalog["reports"]["tool_count"] == 2
    assert available_groups(modules) == ["core", "reports", "security"]


def test_select_tools_by_group_and_dedupes():
    async def a(client): ...
    async def b(client): ...
    m1 = ToolModule("network", "m1", "core", (a, b))
    m2 = ToolModule("network", "m2", "security", (a,))
    assert [f.__name__ for f in select_tools([m1, m2])] == ["a", "b"]
    assert [f.__name__ for f in select_tools([m1, m2], ["security"])] == ["a"]
    assert select_tools([m1, m2], []) == []


# --- resolve_groups ---

@pytest.mark.parametrize("requested", [None, [], ["all"], ["ALL"], ["network:all"]])
def test_resolve_groups_defaults_to_all(requested):
    selected, error = resolve_groups("network", requested, ["core", "security"])
    assert error is None
    assert selected == frozenset({"core", "security"})


def test_resolve_groups_normalizes_and_accepts_prefix():
    selected, error = resolve_groups("network", [" Core ", "network:security"],
                                     ["core", "security", "insights"])
    assert error is None
    assert selected == frozenset({"core", "security"})


def test_resolve_groups_accepts_bare_string():
    selected, error = resolve_groups("network", "core", ["core", "security"])
    assert (selected, error) == (frozenset({"core"}), None)


def test_resolve_groups_unknown_group_lists_available():
    selected, error = resolve_groups("network", ["core", "bogus"], ["core", "security"],
                                     source="UNIFI_TOOL_GROUPS")
    assert selected == frozenset()
    assert "bogus" in error and "core, security" in error
    assert "UNIFI_TOOL_GROUPS" in error


@pytest.mark.parametrize("bad", [["protect:cameras"], [""], [5], ["  "]])
def test_resolve_groups_rejects_bad_entries(bad):
    selected, error = resolve_groups("network", bad, ["core"])
    assert selected == frozenset()
    assert error.startswith("Invalid groups")


# --- tiers ---

def test_module_tier2_tools_merges_declared_and_legacy(fake_package):
    modules = {m.name: m for m in discover_tool_modules("network", package=fake_package)}
    assert dict(modules["reports"].tier2) == {"wipe_report": "reports"}
    # Legacy map applies to network.firewall, but only for exported tools.
    assert dict(modules["firewall"].tier2) == {"create_firewall_rule": "firewall"}
    assert dict(modules["oddities"].tier2) == {}


def test_module_tier2_declaration_overrides_legacy_category():
    async def create_network(client, confirm: bool = False): ...

    class Mod:
        TOOLS = [create_network]
        TIER2_TOOLS = {"create_network": "networks_v2"}

    assert module_tier2_tools("network", "networks", Mod) == {"create_network": "networks_v2"}


def test_module_tier2_ignores_non_mapping_declaration():
    class Mod:
        TOOLS = []
        TIER2_TOOLS = ["not", "a", "mapping"]

    assert module_tier2_tools("network", "whatever", Mod) == {}


def test_moved_legacy_tool_follows_new_module():
    """A legacy Tier 2 name exported by a different module takes that module's tier."""
    async def set_camera_recording_mode(client, camera_id: str): ...

    class NewModule:
        TOOLS = [set_camera_recording_mode]
        TIER2_TOOLS = {}

    assert module_tier2_tools("protect", "camera_controls", NewModule) == {}
    module = _registry._build_module("protect", "camera_controls", NewModule)
    manager = SafetyManager()
    assert manager.get_tier("set_camera_recording_mode") == SafetyTier.PREVIEW_CONFIRM  # legacy baseline
    merge_module_tiers(manager, [module])
    assert manager.get_tier("set_camera_recording_mode") == SafetyTier.EXECUTE


def test_merge_module_tiers_into_safety_manager(fake_package):
    manager = SafetyManager()
    assert manager.get_tier("wipe_report") == SafetyTier.EXECUTE
    merge_module_tiers(manager, discover_tool_modules("network", package=fake_package))
    assert manager.get_tier("wipe_report") == SafetyTier.PREVIEW_CONFIRM
    assert manager.get_category("wipe_report") == "reports"
    assert manager.get_tier("get_report") == SafetyTier.EXECUTE


def test_tool_module_is_immutable():
    module = ToolModule("network", "m", "core", ())
    with pytest.raises(Exception):
        module.group = "security"  # type: ignore[misc]
    with pytest.raises(TypeError):
        module.tier2["x"] = "y"  # type: ignore[index]
    assert module.key == "network.m"


# --- load_product_tools ---

def test_load_product_tools_all_and_by_group():
    everything = load_product_tools("network")
    core = load_product_tools("network", ["core"])
    names = {f.__name__ for f in core}
    assert "get_system_info" in names
    assert "list_firewall_rules" not in names
    assert len(core) < len(everything)


def test_load_product_tools_unknown_product():
    with pytest.raises(ValueError, match="Unknown product"):
        load_product_tools("nonexistent")


def test_no_duplicate_tool_names_across_products():
    seen: dict[str, str] = {}
    duplicates = []
    for product in PRODUCTS:
        for module in discover_tool_modules(product):
            for name in module.tool_names:
                if name in seen:
                    duplicates.append((name, seen[name], module.key))
                seen[name] = module.key
    assert not duplicates, f"Duplicate tool names: {duplicates}"


def test_every_discovered_tool_is_async_with_client_first():
    for product in PRODUCTS:
        for module in discover_tool_modules(product):
            for fn in module.tools:
                assert inspect.iscoroutinefunction(fn), f"{module.key}.{fn.__name__}"
                first = next(iter(inspect.signature(fn).parameters), None)
                assert first == "client", f"{module.key}.{fn.__name__}"


# --- ProductRegistry bookkeeping ---

def test_product_not_loaded_initially():
    registry = ProductRegistry()
    assert registry.is_loaded("network") is False
    assert registry.loaded_groups("network") == frozenset()


def test_mark_loaded():
    registry = ProductRegistry()
    registry.mark_loaded("network", 72)
    assert registry.is_loaded("network") is True


def test_get_load_summary():
    registry = ProductRegistry()
    registry.mark_loaded("network", 72)
    summary = registry.get_summary()
    assert summary["network"] == {"loaded": True, "tool_count": 72, "groups": []}
    assert summary["protect"] == {"loaded": False, "tool_count": 0, "groups": []}
    assert summary["access"] == {"loaded": False, "tool_count": 0, "groups": []}


def test_record_load_is_incremental_and_dedupes():
    registry = ProductRegistry()
    registry.record_load("network", {"core"}, ["a", "b"])
    before = registry.registered_tools
    registry.record_load("network", {"security"}, ["b", "c", "c"])
    assert before == frozenset({"a", "b"})  # earlier snapshot is not mutated
    assert registry.registered_tools == frozenset({"a", "b", "c"})
    assert registry.is_registered("c") is True
    assert registry.loaded_groups("network") == frozenset({"core", "security"})
    summary = registry.get_summary()["network"]
    assert summary == {"loaded": True, "tool_count": 3, "groups": ["core", "security"]}


def test_group_report_marks_loaded_groups():
    registry = ProductRegistry()
    registry.record_load("network", {"core"}, [])
    report = registry.group_report()
    network = {g["group"]: g for g in report["products"]["network"]}
    assert network["core"]["loaded"] is True
    assert network["security"]["loaded"] is False
    assert network["core"]["tool_count"] > 0
    assert "system" in network["core"]["modules"]
    assert set(report["products"]) == set(PRODUCTS)
    assert isinstance(report["skipped_modules"], list)


def test_group_report_lists_skipped_modules(fake_package, monkeypatch):
    real_scan = _registry.scan_tool_modules
    monkeypatch.setattr(
        _registry, "scan_tool_modules",
        lambda product, **kw: real_scan(product, package=fake_package),
    )
    report = ProductRegistry().group_report(products=["network"])
    assert report["skipped_modules"] == [
        {"product": "network", "module": "broken",
         "error": report["skipped_modules"][0]["error"]},
    ]
    assert "ModuleNotFoundError" in report["skipped_modules"][0]["error"]


def test_discover_module_names_plain_module_is_empty(tmp_path, monkeypatch):
    name = f"fake_tools_{uuid.uuid4().hex[:12]}"
    (tmp_path / name).mkdir()
    (tmp_path / name / "__init__.py").write_text("")
    (tmp_path / name / "network.py").write_text("X = 1\n")  # a module, not a package
    monkeypatch.syspath_prepend(str(tmp_path))
    assert discover_module_names("network", package=name) == []


def test_resolve_groups_truncates_echoed_names():
    _, error = resolve_groups("network", ["x" * 500], ["core"])
    assert "x" * 40 in error and "x" * 41 not in error


def test_registry_products_is_a_copy():
    registry = ProductRegistry()
    registry.products["network"].append("injected")
    registry.products["bogus"] = []
    assert "injected" not in PRODUCT_MODULES["network"]
    assert "bogus" not in PRODUCT_MODULES


def test_module_tier2_drops_invalid_entries(capsys):
    async def wipe(client, confirm: bool = False): ...

    class Mod:
        TOOLS = [wipe]
        TIER2_TOOLS = {"wipe": "things", "bad": None, 3: "x", "": "y"}

    assert module_tier2_tools("network", "mod", Mod) == {"wipe": "things"}
    assert "ignored invalid TIER2_TOOLS" in capsys.readouterr().err
    # The merged result is always safe to apply.
    SafetyManager().apply_tool_tiers(["wipe"], module_tier2_tools("network", "mod", Mod))
