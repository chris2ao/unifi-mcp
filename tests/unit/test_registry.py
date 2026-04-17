import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from unifi_mcp.tools._registry import ProductRegistry


def test_registry_knows_product_modules():
    registry = ProductRegistry()
    assert "network" in registry.products
    assert "protect" in registry.products
    assert "access" in registry.products


def test_network_has_expected_modules():
    registry = ProductRegistry()
    modules = registry.products["network"]
    assert "system" in modules
    assert "devices" in modules
    assert "clients" in modules
    assert "firewall" in modules
    assert "zbf" in modules
    assert "topology" in modules
    assert "traffic_flows" in modules


def test_product_not_loaded_initially():
    registry = ProductRegistry()
    assert registry.is_loaded("network") is False


def test_mark_loaded():
    registry = ProductRegistry()
    registry.mark_loaded("network", 72)
    assert registry.is_loaded("network") is True


def test_reload_returns_already_loaded():
    registry = ProductRegistry()
    registry.mark_loaded("network", 72)
    assert registry.is_loaded("network") is True


def test_get_load_summary():
    registry = ProductRegistry()
    registry.mark_loaded("network", 72)
    summary = registry.get_summary()
    assert summary["network"] == {"loaded": True, "tool_count": 72}
    assert summary["protect"] == {"loaded": False, "tool_count": 0}
    assert summary["access"] == {"loaded": False, "tool_count": 0}
