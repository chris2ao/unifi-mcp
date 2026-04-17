import pytest
from unifi_mcp.safety import SafetyManager, SafetyTier


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
