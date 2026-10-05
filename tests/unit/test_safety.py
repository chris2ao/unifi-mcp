import inspect

import pytest

from unifi_mcp.safety import (
    _TIER2_TOOLS,
    SafetyManager,
    SafetyTier,
    mask_secrets,
    params_hash,
)


def test_classify_read_tool_as_tier1():
    manager = SafetyManager()
    assert manager.get_tier("list_devices") == SafetyTier.EXECUTE


def test_classify_destructive_tool_as_tier2():
    manager = SafetyManager()
    assert manager.get_tier("create_network") == SafetyTier.PREVIEW_CONFIRM
    assert manager.get_tier("delete_network") == SafetyTier.PREVIEW_CONFIRM
    assert manager.get_tier("restart_device") == SafetyTier.PREVIEW_CONFIRM
    assert manager.get_tier("block_client") == SafetyTier.PREVIEW_CONFIRM


def test_unknown_tool_defaults_to_tier1():
    manager = SafetyManager()
    assert manager.get_tier("some_new_tool") == SafetyTier.EXECUTE


def test_preview_log_records_preview():
    manager = SafetyManager()
    manager.record_preview("create_network", {"name": "IoT", "vlan": 100})
    assert manager.has_preview("create_network")


def test_confirm_requires_prior_preview():
    manager = SafetyManager()
    assert manager.has_preview("create_network") is False


def test_preview_log_clears_after_confirm():
    manager = SafetyManager()
    manager.record_preview("create_network", {"name": "IoT"})
    manager.confirm_executed("create_network")
    assert manager.has_preview("create_network") is False


def test_mutation_log_records_execution():
    manager = SafetyManager()
    manager.log_mutation("create_network", {"name": "IoT"}, {"_id": "abc"})
    log = manager.get_mutation_log()
    assert len(log) == 1
    assert log[0]["tool"] == "create_network"
    assert log[0]["params"] == {"name": "IoT"}
    assert log[0]["result"] == {"_id": "abc"}
    assert "timestamp" in log[0]


def test_get_category_for_tool():
    manager = SafetyManager()
    assert manager.get_category("create_network") == "networks"
    assert manager.get_category("restart_device") == "devices"
    assert manager.get_category("list_devices") is None


# --- v0.5.1: enforced preview-confirm support ---


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_params_hash_is_order_independent_and_value_sensitive():
    a = params_hash({"name": "IoT", "vlan": 100})
    b = params_hash({"vlan": 100, "name": "IoT"})
    c = params_hash({"name": "IoT", "vlan": 101})
    assert a == b
    assert a != c
    assert len(a) == 64


def test_params_hash_handles_non_json_values():
    assert params_hash({"when": object.__new__(object)}) is not None


def test_consume_preview_matches_exact_params_once():
    manager = SafetyManager(clock=FakeClock())
    manager.record_preview("create_network", {"name": "IoT", "vlan": 100})
    assert manager.consume_preview("create_network", {"name": "IoT", "vlan": 101}) is False
    assert manager.consume_preview("delete_network", {"name": "IoT", "vlan": 100}) is False
    assert manager.consume_preview("create_network", {"vlan": 100, "name": "IoT"}) is True
    assert manager.consume_preview("create_network", {"name": "IoT", "vlan": 100}) is False


def test_consume_preview_rejects_expired():
    clock = FakeClock()
    manager = SafetyManager(clock=clock, preview_ttl_seconds=60)
    manager.record_preview("delete_wlan", {"wlan_id": "w1"})
    clock.now += 61
    assert manager.consume_preview("delete_wlan", {"wlan_id": "w1"}) is False
    # The expired record is discarded, not left to linger.
    clock.now -= 61
    assert manager.consume_preview("delete_wlan", {"wlan_id": "w1"}) is False


def test_consume_preview_accepts_at_ttl_boundary():
    clock = FakeClock()
    manager = SafetyManager(clock=clock, preview_ttl_seconds=60)
    manager.record_preview("delete_wlan", {"wlan_id": "w1"})
    clock.now += 60
    assert manager.consume_preview("delete_wlan", {"wlan_id": "w1"}) is True


def test_record_preview_refreshes_timestamp():
    clock = FakeClock()
    manager = SafetyManager(clock=clock, preview_ttl_seconds=60)
    manager.record_preview("toggle_wlan", {"wlan_id": "w1"})
    clock.now += 50
    manager.record_preview("toggle_wlan", {"wlan_id": "w1"})
    clock.now += 50
    assert manager.consume_preview("toggle_wlan", {"wlan_id": "w1"}) is True


def test_multiple_outstanding_previews_per_tool():
    manager = SafetyManager(clock=FakeClock())
    manager.record_preview("delete_wlan", {"wlan_id": "w1"})
    manager.record_preview("delete_wlan", {"wlan_id": "w2"})
    assert manager.consume_preview("delete_wlan", {"wlan_id": "w2"}) is True
    assert manager.consume_preview("delete_wlan", {"wlan_id": "w1"}) is True


def test_has_preview_with_params_and_expiry():
    clock = FakeClock()
    manager = SafetyManager(clock=clock, preview_ttl_seconds=10)
    manager.record_preview("delete_wlan", {"wlan_id": "w1"})
    assert manager.has_preview("delete_wlan", {"wlan_id": "w1"}) is True
    assert manager.has_preview("delete_wlan", {"wlan_id": "w2"}) is False
    clock.now += 11
    assert manager.has_preview("delete_wlan") is False


def test_confirm_executed_with_params_clears_only_that_preview():
    manager = SafetyManager(clock=FakeClock())
    manager.record_preview("delete_wlan", {"wlan_id": "w1"})
    manager.record_preview("delete_wlan", {"wlan_id": "w2"})
    manager.confirm_executed("delete_wlan", {"wlan_id": "w1"})
    assert manager.has_preview("delete_wlan", {"wlan_id": "w1"}) is False
    assert manager.has_preview("delete_wlan", {"wlan_id": "w2"}) is True


def test_preview_store_is_bounded():
    clock = FakeClock()
    manager = SafetyManager(clock=clock, max_previews=5)
    for i in range(8):
        clock.now += 1
        manager.record_preview("delete_wlan", {"wlan_id": f"w{i}"})
    assert manager.has_preview("delete_wlan", {"wlan_id": "w0"}) is False
    assert manager.has_preview("delete_wlan", {"wlan_id": "w2"}) is False
    assert manager.has_preview("delete_wlan", {"wlan_id": "w3"}) is True
    assert manager.has_preview("delete_wlan", {"wlan_id": "w7"}) is True


def test_preview_ttl_must_be_positive():
    with pytest.raises(ValueError):
        SafetyManager(preview_ttl_seconds=0)


def test_mask_secrets_masks_secret_looking_keys_recursively():
    params = {
        "name": "Guest",
        "x_passphrase": "hunter2",
        "passphrase": "hunter2",
        "Password": "p",
        "radius_secret": "s",
        "api_key": "k",
        "auth_token": "t",
        "wpa_psk": "w",
        "x_iapp_key": "i",
        "nested": {"secret": "s", "ok": 1, "items": [{"token": "t", "vlan": 5}]},
        "list": ["plain", {"psk": "z"}],
        "count": 3,
    }
    masked = mask_secrets(params)
    for key in ("x_passphrase", "passphrase", "Password", "radius_secret", "api_key",
                "auth_token", "wpa_psk", "x_iapp_key"):
        assert masked[key] == "***", key
    assert masked["name"] == "Guest"
    assert masked["count"] == 3
    assert masked["nested"]["secret"] == "***"
    assert masked["nested"]["ok"] == 1
    assert masked["nested"]["items"][0] == {"token": "***", "vlan": 5}
    assert masked["list"] == ["plain", {"psk": "***"}]
    # Input untouched.
    assert params["x_passphrase"] == "hunter2"
    assert params["nested"]["items"][0]["token"] == "t"


def test_mutation_log_masks_and_returns_copies():
    manager = SafetyManager()
    manager.log_mutation("create_wlan", {"name": "Guest", "x_passphrase": "hunter2"},
                         {"executed": True})
    log = manager.get_mutation_log()
    assert log[0]["params"] == {"name": "Guest", "x_passphrase": "***"}
    log[0]["params"]["name"] = "changed"
    log.append({"bogus": True})
    fresh = manager.get_mutation_log()
    assert len(fresh) == 1
    assert fresh[0]["params"]["name"] == "Guest"


def test_mutation_log_is_bounded():
    manager = SafetyManager(max_log_entries=3)
    for i in range(5):
        manager.log_mutation("delete_wlan", {"wlan_id": f"w{i}"}, {"executed": True})
    log = manager.get_mutation_log()
    assert [e["params"]["wlan_id"] for e in log] == ["w2", "w3", "w4"]


def test_tier2_includes_traffic_rules_and_protect_confirm_tools():
    manager = SafetyManager()
    for name in ("create_traffic_rule", "update_traffic_rule",
                 "delete_traffic_rule", "toggle_traffic_rule"):
        assert manager.get_tier(name) == SafetyTier.PREVIEW_CONFIRM
        assert manager.get_category(name) == "traffic_rules"
    for name in ("set_camera_recording_mode", "ptz_camera", "reboot_camera"):
        assert manager.get_tier(name) == SafetyTier.PREVIEW_CONFIRM


def test_tier2_has_no_phantom_vpn_tools():
    for name in ("create_vpn", "update_vpn", "delete_vpn"):
        assert name not in _TIER2_TOOLS


def _has_confirm(fn) -> bool:
    return "confirm" in inspect.signature(fn).parameters


def _discovered_modules():
    from unifi_mcp.tools._registry import PRODUCTS, discover_tool_modules

    # strict: a module that fails to import must fail this test, not vanish from it
    return [
        module
        for product in (*PRODUCTS, "cloud")
        for module in discover_tool_modules(product, strict=True)
    ]


def test_confirm_param_tools_equal_merged_tier2_tools():
    """Every auto-discovered tool has a confirm param exactly when the merged map says Tier 2.

    The merged map is the legacy per-module declarations in safety.py plus each
    module's own TIER2_TOOLS, applied the way the server applies them on load.
    """
    from unifi_mcp.tools._registry import merge_module_tiers

    modules = _discovered_modules()
    manager = SafetyManager()
    merge_module_tiers(manager, modules)

    tools = [fn for module in modules for fn in module.tools]
    assert tools, "auto-discovery found no tools"
    confirm_tools = {fn.__name__ for fn in tools if _has_confirm(fn)}
    tier2_tools = {
        fn.__name__ for fn in tools
        if manager.get_tier(fn.__name__) == SafetyTier.PREVIEW_CONFIRM
    }
    missing = confirm_tools - tier2_tools
    assert not missing, f"Tools with confirm param missing from Tier 2: {sorted(missing)}"
    extra = tier2_tools - confirm_tools
    assert not extra, f"Tier 2 tools without a confirm param: {sorted(extra)}"
    for name in tier2_tools:
        assert manager.get_category(name), name


def test_module_tier2_declarations_name_confirm_tools_in_that_module():
    """A module's TIER2_TOOLS may only name its own confirm tools (catches typos)."""
    phantom = []
    for module in _discovered_modules():
        own_confirm = {fn.__name__ for fn in module.tools if _has_confirm(fn)}
        phantom.extend(f"{module.key}:{name}" for name in module.tier2 if name not in own_confirm)
    assert not phantom, f"Tier 2 entries without a matching confirm tool: {sorted(phantom)}"


def test_legacy_map_is_keyed_by_product_module():
    from unifi_mcp.safety import _LEGACY_TIER2_BY_MODULE, legacy_tier2_for

    for key, mapping in _LEGACY_TIER2_BY_MODULE.items():
        product, _, module = key.partition(".")
        assert product in ("network", "protect") and module, key
        assert mapping, key
    flat = {n: c for m in _LEGACY_TIER2_BY_MODULE.values() for n, c in m.items()}
    assert flat == _TIER2_TOOLS
    copy_ = legacy_tier2_for("network.networks")
    copy_["injected"] = "x"
    assert "injected" not in legacy_tier2_for("network.networks")
    assert legacy_tier2_for("network.nope") == {}


def test_apply_tool_tiers_adds_and_demotes():
    manager = SafetyManager()
    before = manager.tier2_tools
    manager.apply_tool_tiers(["new_write", "ptz_camera", "get_x"], {"new_write": "things"})
    assert manager.get_tier("new_write") == SafetyTier.PREVIEW_CONFIRM
    assert manager.get_category("new_write") == "things"
    # A legacy Tier 2 name listed as one of the module's tools but not declared is demoted.
    assert manager.get_tier("ptz_camera") == SafetyTier.EXECUTE
    assert manager.get_tier("get_x") == SafetyTier.EXECUTE
    # Tools outside the call keep their tier.
    assert manager.get_tier("create_network") == SafetyTier.PREVIEW_CONFIRM
    # Earlier snapshots are copies, not views.
    assert before["ptz_camera"] == "protect_cameras"
    assert "new_write" not in before


def test_apply_tool_tiers_declared_category_wins():
    manager = SafetyManager()
    manager.apply_tool_tiers(["create_network"], {"create_network": "networks_v2"})
    assert manager.get_category("create_network") == "networks_v2"


def test_apply_tool_tiers_does_not_affect_other_managers():
    first, second = SafetyManager(), SafetyManager()
    first.apply_tool_tiers(["only_here"], {"only_here": "x"})
    assert second.get_tier("only_here") == SafetyTier.EXECUTE


@pytest.mark.parametrize("bad", [{"": "x"}, {"a": ""}, {"a": 1}, {1: "x"}])
def test_apply_tool_tiers_rejects_bad_entries(bad):
    with pytest.raises(ValueError):
        SafetyManager().apply_tool_tiers([], bad)


def test_apply_tool_tiers_rejects_non_mapping():
    with pytest.raises(TypeError):
        SafetyManager().apply_tool_tiers([], [("a", "b")])


def test_tier2_tools_property_returns_copy():
    manager = SafetyManager()
    snapshot = manager.tier2_tools
    snapshot["fake"] = "x"
    assert manager.get_tier("fake") == SafetyTier.EXECUTE


def test_params_hash_treats_integral_floats_as_ints():
    from unifi_mcp.safety import params_hash

    assert params_hash({"updates": {"v": 1}}) == params_hash({"updates": {"v": 1.0}})
    assert params_hash({"v": 1.5}) != params_hash({"v": 1})


def test_bounds_must_be_positive():
    import pytest as _pytest
    from unifi_mcp.safety import SafetyManager

    with _pytest.raises(ValueError):
        SafetyManager(max_previews=0)
    with _pytest.raises(ValueError):
        SafetyManager(max_log_entries=0)
