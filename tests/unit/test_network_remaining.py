"""Tests for remaining network tool modules: radius, port_profiles, backups,
vpn, port_forwarding, dpi, hotspot, mac_acl, qos, webhooks."""

import json
import pytest
import httpx
import respx
from pathlib import Path

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.discovery import DiscoveryRegistry

FIXTURES = Path(__file__).parent.parent / "fixtures"
BASE = "https://192.168.1.1"


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", BASE)
    monkeypatch.setenv("UNIFI_API_KEY", "test-key")
    return UnifiConfig()


@pytest.fixture
def mock_client(config):
    return UnifiClient(config, TTLCache(), DiscoveryRegistry())


# --- RADIUS ---

@respx.mock
@pytest.mark.asyncio
async def test_list_radius_profiles(mock_client):
    from unifi_mcp.tools.network.radius import list_radius_profiles

    respx.get(f"{BASE}/proxy/network/api/s/default/rest/radiusprofile").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "rad001", "name": "Corp RADIUS", "auth_servers": [{"ip": "10.0.0.5", "port": 1812}]}
        ]})
    )
    result = await list_radius_profiles(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "Corp RADIUS"


@respx.mock
@pytest.mark.asyncio
async def test_create_radius_profile_preview(mock_client):
    from unifi_mcp.tools.network.radius import create_radius_profile

    result = await create_radius_profile(
        mock_client,
        name="Test RADIUS",
        auth_servers=[{"ip": "10.0.0.10", "port": 1812, "x_secret": "secret"}],
        confirm=False,
    )
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_radius_profile_preview(mock_client):
    from unifi_mcp.tools.network.radius import delete_radius_profile

    result = await delete_radius_profile(mock_client, profile_id="rad001", confirm=False)
    assert result["preview"] is True


def test_radius_tools_list():
    from unifi_mcp.tools.network.radius import TOOLS
    assert len(TOOLS) == 4


# --- Port Profiles ---

@respx.mock
@pytest.mark.asyncio
async def test_list_port_profiles(mock_client):
    from unifi_mcp.tools.network.port_profiles import list_port_profiles

    respx.get(f"{BASE}/proxy/network/api/s/default/rest/portconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "pp001", "name": "All", "native_networkconf_id": "net001", "poe_mode": "auto"}
        ]})
    )
    result = await list_port_profiles(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "All"


@respx.mock
@pytest.mark.asyncio
async def test_create_port_profile_preview(mock_client):
    from unifi_mcp.tools.network.port_profiles import create_port_profile

    result = await create_port_profile(
        mock_client,
        name="IoT Profile",
        native_networkconf_id="net002",
        confirm=False,
    )
    assert result["preview"] is True


def test_port_profiles_tools_list():
    from unifi_mcp.tools.network.port_profiles import TOOLS
    assert len(TOOLS) == 4


# --- Backups ---

@respx.mock
@pytest.mark.asyncio
async def test_list_backups(mock_client):
    from unifi_mcp.tools.network.backups import list_backups

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/backup").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"filename": "backup_2026-04-14.unf", "time": 1713100000, "size": 52428800}
        ]})
    )
    result = await list_backups(mock_client)
    assert len(result) == 1
    assert result[0]["filename"] == "backup_2026-04-14.unf"


@respx.mock
@pytest.mark.asyncio
async def test_create_backup(mock_client):
    from unifi_mcp.tools.network.backups import create_backup

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/backup").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": []})
    )
    result = await create_backup(mock_client)
    assert result["action"] == "create_backup"


@respx.mock
@pytest.mark.asyncio
async def test_restore_backup_preview(mock_client):
    from unifi_mcp.tools.network.backups import restore_backup

    result = await restore_backup(mock_client, filename="backup.unf", confirm=False)
    assert result["preview"] is True


def test_backups_tools_list():
    from unifi_mcp.tools.network.backups import TOOLS
    assert len(TOOLS) == 3


# --- VPN ---

@respx.mock
@pytest.mark.asyncio
async def test_list_vpn_servers(mock_client):
    from unifi_mcp.tools.network.vpn import list_vpn_servers

    respx.get(f"{BASE}/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "vpn001", "name": "WireGuard Server", "purpose": "vpn-server", "enabled": True},
            {"_id": "net001", "name": "Default", "purpose": "corporate"}
        ]})
    )
    result = await list_vpn_servers(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "WireGuard Server"


@respx.mock
@pytest.mark.asyncio
async def test_list_vpn_clients(mock_client):
    from unifi_mcp.tools.network.vpn import list_vpn_clients

    respx.get(f"{BASE}/proxy/network/api/s/default/rest/networkconf").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "vpn002", "name": "Site-to-Site", "purpose": "vpn-client", "enabled": True},
            {"_id": "net001", "name": "Default", "purpose": "corporate"}
        ]})
    )
    result = await list_vpn_clients(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "Site-to-Site"


def test_vpn_tools_list():
    from unifi_mcp.tools.network.vpn import TOOLS
    assert len(TOOLS) == 2


# --- Port Forwarding ---

@respx.mock
@pytest.mark.asyncio
async def test_list_port_forwards(mock_client):
    from unifi_mcp.tools.network.port_forwarding import list_port_forwards

    respx.get(f"{BASE}/proxy/network/api/s/default/rest/portforward").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "pf001", "name": "Web Server", "fwd_ip": "192.168.1.50", "fwd_port": "80", "dst_port": "80", "proto": "tcp", "enabled": True}
        ]})
    )
    result = await list_port_forwards(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "Web Server"


@respx.mock
@pytest.mark.asyncio
async def test_create_port_forward_preview(mock_client):
    from unifi_mcp.tools.network.port_forwarding import create_port_forward

    result = await create_port_forward(
        mock_client,
        name="SSH",
        fwd_ip="192.168.1.50",
        fwd_port="22",
        dst_port="2222",
        proto="tcp",
        confirm=False,
    )
    assert result["preview"] is True


@respx.mock
@pytest.mark.asyncio
async def test_delete_port_forward_preview(mock_client):
    from unifi_mcp.tools.network.port_forwarding import delete_port_forward

    result = await delete_port_forward(mock_client, rule_id="pf001", confirm=False)
    assert result["preview"] is True


def test_port_forwarding_tools_list():
    from unifi_mcp.tools.network.port_forwarding import TOOLS
    assert len(TOOLS) == 4


# --- DPI ---

@respx.mock
@pytest.mark.asyncio
async def test_get_dpi_stats(mock_client):
    from unifi_mcp.tools.network.dpi import get_dpi_stats

    respx.get(f"{BASE}/proxy/network/api/s/default/stat/dpi").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"cat": 5, "app": 94, "rx_bytes": 1048576, "tx_bytes": 524288}
        ]})
    )
    result = await get_dpi_stats(mock_client)
    assert len(result) == 1


@respx.mock
@pytest.mark.asyncio
async def test_get_dpi_by_app(mock_client):
    from unifi_mcp.tools.network.dpi import get_dpi_by_app

    respx.post(f"{BASE}/proxy/network/api/s/default/stat/stadpi").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"mac": "AA:BB:CC:DD:EE:01", "by_app": [{"app": 94, "rx_bytes": 1024, "tx_bytes": 512}]}
        ]})
    )
    result = await get_dpi_by_app(mock_client, mac="AA:BB:CC:DD:EE:01")
    assert len(result) == 1


def test_dpi_tools_list():
    from unifi_mcp.tools.network.dpi import TOOLS
    assert len(TOOLS) == 2


# --- Hotspot / Vouchers ---

@respx.mock
@pytest.mark.asyncio
async def test_list_vouchers(mock_client):
    from unifi_mcp.tools.network.hotspot import list_vouchers

    respx.get(f"{BASE}/proxy/network/api/s/default/stat/voucher").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "v001", "code": "12345-67890", "quota": 1, "duration": 1440, "used": 0, "note": "Guest pass"}
        ]})
    )
    result = await list_vouchers(mock_client)
    assert len(result) == 1
    assert result[0]["code"] == "12345-67890"


@respx.mock
@pytest.mark.asyncio
async def test_create_voucher(mock_client):
    from unifi_mcp.tools.network.hotspot import create_voucher

    respx.post(f"{BASE}/proxy/network/api/s/default/cmd/hotspot").mock(
        return_value=httpx.Response(200, json={"meta": {"rc": "ok"}, "data": [
            {"_id": "v_new", "code": "99999-00000", "create_time": 1713100000}
        ]})
    )
    result = await create_voucher(mock_client, expire_minutes=1440, quota=1)
    assert result["action"] == "create_voucher"


def test_hotspot_tools_list():
    from unifi_mcp.tools.network.hotspot import TOOLS
    assert len(TOOLS) == 2


# --- MAC ACL ---

@respx.mock
@pytest.mark.asyncio
async def test_list_mac_filter(mock_client):
    from unifi_mcp.tools.network.mac_acl import list_mac_filter

    respx.get(f"{BASE}/proxy/network/v2/api/site/default/acl-rules").mock(
        return_value=httpx.Response(200, json={"data": [
            {"_id": "acl001", "name": "Block Rogue", "action": "block", "mac_addresses": ["AA:BB:CC:DD:EE:FF"]}
        ]})
    )
    result = await list_mac_filter(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "Block Rogue"


@pytest.mark.asyncio
async def test_add_mac_filter_preview(mock_client):
    from unifi_mcp.tools.network.mac_acl import add_mac_filter

    result = await add_mac_filter(
        mock_client,
        name="New ACL",
        action="block",
        mac_addresses=["11:22:33:44:55:66"],
        confirm=False,
    )
    assert result["preview"] is True
    assert result["action"] == "add_mac_filter"


@respx.mock
@pytest.mark.asyncio
async def test_add_mac_filter_confirm(mock_client):
    from unifi_mcp.tools.network.mac_acl import add_mac_filter

    respx.post(f"{BASE}/proxy/network/v2/api/site/default/acl-rules").mock(
        return_value=httpx.Response(200, json={"data": {"_id": "acl_new", "name": "New ACL"}})
    )
    result = await add_mac_filter(
        mock_client,
        name="New ACL",
        action="block",
        mac_addresses=["11:22:33:44:55:66"],
        confirm=True,
    )
    assert result["executed"] is True
    assert result["action"] == "add_mac_filter"


@pytest.mark.asyncio
async def test_delete_mac_filter_preview(mock_client):
    from unifi_mcp.tools.network.mac_acl import delete_mac_filter

    result = await delete_mac_filter(mock_client, rule_id="acl001", confirm=False)
    assert result["preview"] is True
    assert result["action"] == "delete_mac_filter"


@respx.mock
@pytest.mark.asyncio
async def test_delete_mac_filter_confirm(mock_client):
    from unifi_mcp.tools.network.mac_acl import delete_mac_filter

    respx.delete(f"{BASE}/proxy/network/v2/api/site/default/acl-rules/acl001").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    result = await delete_mac_filter(mock_client, rule_id="acl001", confirm=True)
    assert result["executed"] is True
    assert result["action"] == "delete_mac_filter"


def test_mac_acl_tools_list():
    from unifi_mcp.tools.network.mac_acl import TOOLS
    assert len(TOOLS) == 3


# --- QoS ---

@respx.mock
@pytest.mark.asyncio
async def test_list_qos_rules(mock_client):
    from unifi_mcp.tools.network.qos import list_qos_rules

    respx.get(f"{BASE}/proxy/network/v2/api/site/default/qos-rules").mock(
        return_value=httpx.Response(200, json={"data": [
            {"_id": "qos001", "name": "VoIP Priority", "enabled": True, "action": "set-dscp", "rate_limit_up": 0, "rate_limit_down": 0}
        ]})
    )
    result = await list_qos_rules(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "VoIP Priority"


@respx.mock
@pytest.mark.asyncio
async def test_get_bandwidth_profiles(mock_client):
    from unifi_mcp.tools.network.qos import get_bandwidth_profiles

    respx.get(f"{BASE}/proxy/network/v2/api/site/default/qos-rules").mock(
        return_value=httpx.Response(200, json={"data": [
            {"_id": "qos001", "name": "VoIP Priority", "enabled": True}
        ]})
    )
    result = await get_bandwidth_profiles(mock_client)
    assert isinstance(result, list)


def test_qos_tools_list():
    from unifi_mcp.tools.network.qos import TOOLS
    assert len(TOOLS) == 2


# --- Webhooks ---

@respx.mock
@pytest.mark.asyncio
async def test_list_webhooks(mock_client):
    from unifi_mcp.tools.network.webhooks import list_webhooks

    respx.get(f"{BASE}/proxy/network/v2/api/site/default/notifications").mock(
        return_value=httpx.Response(200, json={"data": [
            {"_id": "wh001", "name": "Alert Hook", "url": "https://hooks.example.com/alert", "enabled": True}
        ]})
    )
    result = await list_webhooks(mock_client)
    assert len(result) == 1
    assert result[0]["name"] == "Alert Hook"


@respx.mock
@pytest.mark.asyncio
async def test_create_webhook(mock_client):
    from unifi_mcp.tools.network.webhooks import create_webhook

    respx.post(f"{BASE}/proxy/network/v2/api/site/default/notifications").mock(
        return_value=httpx.Response(200, json={"data": {"_id": "wh_new", "name": "New Hook"}})
    )
    result = await create_webhook(mock_client, name="New Hook", url="https://hooks.example.com/new")
    assert result["action"] == "create_webhook"


@respx.mock
@pytest.mark.asyncio
async def test_delete_webhook(mock_client):
    from unifi_mcp.tools.network.webhooks import delete_webhook

    respx.delete(f"{BASE}/proxy/network/v2/api/site/default/notifications/wh001").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    result = await delete_webhook(mock_client, webhook_id="wh001")
    assert result["action"] == "delete_webhook"


def test_webhooks_tools_list():
    from unifi_mcp.tools.network.webhooks import TOOLS
    assert len(TOOLS) == 3
