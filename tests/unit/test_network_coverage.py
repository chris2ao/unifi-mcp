"""Additional tests to cover confirmed execution paths (Tier 2 tools)
and other untested branches to reach 80% coverage."""

import json
import pytest
import httpx
import respx
from pathlib import Path

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry

BASE = "https://192.168.1.1"
OK_RESPONSE = {"meta": {"rc": "ok"}, "data": []}


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


# --- Firewall confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_update_firewall_rule_confirmed(mock_client):
    from unifi_mcp.tools.network.firewall import update_firewall_rule

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/firewallrule/fw001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await update_firewall_rule(mock_client, rule_id="fw001", updates={"enabled": False}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_firewall_rule_confirmed(mock_client):
    from unifi_mcp.tools.network.firewall import delete_firewall_rule

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/firewallrule/fw001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_firewall_rule(mock_client, rule_id="fw001", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_reorder_firewall_rules_confirmed(mock_client):
    from unifi_mcp.tools.network.firewall import reorder_firewall_rules

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/firewallrule/fw001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await reorder_firewall_rules(mock_client, rule_id="fw001", new_index=500, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_create_firewall_group_confirmed(mock_client):
    from unifi_mcp.tools.network.firewall import create_firewall_group

    respx.post(f"{BASE}/proxy/network/api/s/default/rest/firewallgroup").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await create_firewall_group(
        mock_client, name="Test", group_type="address-group", members=["10.0.0.1"], confirm=True
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_firewall_group_confirmed(mock_client):
    from unifi_mcp.tools.network.firewall import delete_firewall_group

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/firewallgroup/fwg001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_firewall_group(mock_client, group_id="fwg001", confirm=True)
    assert result["executed"] is True


# --- ZBF confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_update_zbf_policy_confirmed(mock_client):
    from unifi_mcp.tools.network.zbf import update_zbf_policy

    respx.put(f"{BASE}/proxy/network/v2/api/site/default/firewall-policies/pol001").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    result = await update_zbf_policy(mock_client, policy_id="pol001", updates={"enabled": False}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_zbf_policy_confirmed(mock_client):
    from unifi_mcp.tools.network.zbf import delete_zbf_policy

    respx.delete(f"{BASE}/proxy/network/v2/api/site/default/firewall-policies/pol001").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    result = await delete_zbf_policy(mock_client, policy_id="pol001", confirm=True)
    assert result["executed"] is True


# --- Networks confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_update_network_preview(mock_client):
    from unifi_mcp.tools.network.networks import update_network

    result = await update_network(mock_client, network_id="net001", updates={"name": "New"}, confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_network_confirmed(mock_client):
    from unifi_mcp.tools.network.networks import update_network

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/networkconf/net001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await update_network(mock_client, network_id="net001", updates={"name": "New"}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_network_confirmed(mock_client):
    from unifi_mcp.tools.network.networks import delete_network

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/networkconf/net002").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_network(mock_client, network_id="net002", confirm=True)
    assert result["executed"] is True


# --- WiFi confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_update_wlan_preview(mock_client):
    from unifi_mcp.tools.network.wifi import update_wlan

    result = await update_wlan(mock_client, wlan_id="wlan001", updates={"name": "New"}, confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_wlan_confirmed(mock_client):
    from unifi_mcp.tools.network.wifi import update_wlan

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/wlanconf/wlan001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await update_wlan(mock_client, wlan_id="wlan001", updates={"name": "New"}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_wlan_confirmed(mock_client):
    from unifi_mcp.tools.network.wifi import delete_wlan

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/wlanconf/wlan001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_wlan(mock_client, wlan_id="wlan001", confirm=True)
    assert result["executed"] is True


# --- Port profiles confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_create_port_profile_confirmed(mock_client):
    from unifi_mcp.tools.network.port_profiles import create_port_profile

    respx.post(f"{BASE}/proxy/network/api/s/default/rest/portconf").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await create_port_profile(mock_client, name="IoT", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_port_profile_preview(mock_client):
    from unifi_mcp.tools.network.port_profiles import update_port_profile

    result = await update_port_profile(mock_client, profile_id="pp001", updates={"poe_mode": "off"}, confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_port_profile_confirmed(mock_client):
    from unifi_mcp.tools.network.port_profiles import update_port_profile

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/portconf/pp001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await update_port_profile(mock_client, profile_id="pp001", updates={"poe_mode": "off"}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_port_profile_preview(mock_client):
    from unifi_mcp.tools.network.port_profiles import delete_port_profile

    result = await delete_port_profile(mock_client, profile_id="pp001", confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_port_profile_confirmed(mock_client):
    from unifi_mcp.tools.network.port_profiles import delete_port_profile

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/portconf/pp001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_port_profile(mock_client, profile_id="pp001", confirm=True)
    assert result["executed"] is True


# --- RADIUS confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_create_radius_profile_confirmed(mock_client):
    from unifi_mcp.tools.network.radius import create_radius_profile

    respx.post(f"{BASE}/proxy/network/api/s/default/rest/radiusprofile").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await create_radius_profile(
        mock_client, name="Test", auth_servers=[{"ip": "10.0.0.5", "port": 1812}], confirm=True
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_radius_profile_preview(mock_client):
    from unifi_mcp.tools.network.radius import update_radius_profile

    result = await update_radius_profile(mock_client, profile_id="rad001", updates={"name": "New"}, confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_radius_profile_confirmed(mock_client):
    from unifi_mcp.tools.network.radius import update_radius_profile

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/radiusprofile/rad001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await update_radius_profile(mock_client, profile_id="rad001", updates={"name": "New"}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_radius_profile_confirmed(mock_client):
    from unifi_mcp.tools.network.radius import delete_radius_profile

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/radiusprofile/rad001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_radius_profile(mock_client, profile_id="rad001", confirm=True)
    assert result["executed"] is True


# --- Port forwarding confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_create_port_forward_confirmed(mock_client):
    from unifi_mcp.tools.network.port_forwarding import create_port_forward

    respx.post(f"{BASE}/proxy/network/api/s/default/rest/portforward").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await create_port_forward(
        mock_client, name="SSH", fwd_ip="192.168.1.50", fwd_port="22", dst_port="2222", confirm=True
    )
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_port_forward_preview(mock_client):
    from unifi_mcp.tools.network.port_forwarding import update_port_forward

    result = await update_port_forward(mock_client, rule_id="pf001", updates={"enabled": False}, confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_update_port_forward_confirmed(mock_client):
    from unifi_mcp.tools.network.port_forwarding import update_port_forward

    respx.put(f"{BASE}/proxy/network/api/s/default/rest/portforward/pf001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await update_port_forward(mock_client, rule_id="pf001", updates={"enabled": False}, confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_port_forward_confirmed(mock_client):
    from unifi_mcp.tools.network.port_forwarding import delete_port_forward

    respx.delete(f"{BASE}/proxy/network/api/s/default/rest/portforward/pf001").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await delete_port_forward(mock_client, rule_id="pf001", confirm=True)
    assert result["executed"] is True


# --- Backups confirmed execution ---

@respx.mock
@pytest.mark.asyncio
async def test_restore_backup_confirmed(mock_client):
    from unifi_mcp.tools.network.backups import restore_backup

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/backup").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await restore_backup(mock_client, filename="backup.unf", confirm=True)
    assert result["executed"] is True


# --- Device confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_adopt_device_confirmed(mock_client):
    from unifi_mcp.tools.network.devices import adopt_device

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await adopt_device(mock_client, mac="00:11:22:33:44:55", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_forget_device_confirmed(mock_client):
    from unifi_mcp.tools.network.devices import forget_device

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await forget_device(mock_client, mac="00:11:22:33:44:55", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_rf_scan_preview(mock_client):
    from unifi_mcp.tools.network.devices import rf_scan

    result = await rf_scan(mock_client, mac="00:11:22:33:44:55", confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_rf_scan_confirmed(mock_client):
    from unifi_mcp.tools.network.devices import rf_scan

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await rf_scan(mock_client, mac="00:11:22:33:44:55", confirm=True)
    assert result["executed"] is True


@respx.mock
@pytest.mark.asyncio
async def test_upgrade_firmware_preview(mock_client):
    from unifi_mcp.tools.network.devices import upgrade_firmware

    result = await upgrade_firmware(mock_client, mac="00:11:22:33:44:55", confirm=False)
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_upgrade_firmware_confirmed(mock_client):
    from unifi_mcp.tools.network.devices import upgrade_firmware

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/devmgr").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await upgrade_firmware(mock_client, mac="00:11:22:33:44:55", confirm=True)
    assert result["executed"] is True


# --- Client confirmed executions ---

@respx.mock
@pytest.mark.asyncio
async def test_unblock_client_confirmed(mock_client):
    from unifi_mcp.tools.network.clients import unblock_client

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/stamgr").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await unblock_client(mock_client, mac="AA:BB:CC:DD:EE:01", confirm=True)
    assert result["executed"] is True


# --- Registry load_product_tools ---

def test_load_product_tools_network():
    from unifi_mcp.tools._registry import load_product_tools

    tools = load_product_tools("network")
    assert len(tools) > 50  # We have 72+ tools across all modules


def test_load_product_tools_unknown():
    from unifi_mcp.tools._registry import load_product_tools

    with pytest.raises(ValueError, match="Unknown product"):
        load_product_tools("nonexistent")


# --- Hotspot note parameter ---

@respx.mock
@pytest.mark.asyncio
async def test_create_voucher_with_note(mock_client):
    from unifi_mcp.tools.network.hotspot import create_voucher

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/hotspot").mock(
        return_value=httpx.Response(200, json=OK_RESPONSE)
    )
    result = await create_voucher(mock_client, expire_minutes=60, quota=1, note="VIP Guest")
    assert result["action"] == "create_voucher"
