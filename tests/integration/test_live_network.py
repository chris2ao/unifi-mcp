"""Integration tests for live UniFi network tool functions.

These tests call real API endpoints against a live console. They are
read-only and safe to run against production hardware.

Requires UNIFI_HOST and UNIFI_API_KEY in the environment.

NOTE: The tool modules imported here (network.system, network.devices) are
built by a parallel agent. Tests are skipped at collection time if those
modules are not yet available.

Run with:
    uv run pytest tests/integration/test_live_network.py -m integration -v -s
"""
import pytest

# Use pytest.importorskip so the whole file is skipped gracefully when the
# tool modules have not been committed yet (parallel agent work-in-progress).
system = pytest.importorskip(
    "unifi_mcp.tools.network.system",
    reason="unifi_mcp.tools.network.system not yet implemented",
)
devices_mod = pytest.importorskip(
    "unifi_mcp.tools.network.devices",
    reason="unifi_mcp.tools.network.devices not yet implemented",
)

get_system_info = system.get_system_info
get_health = system.get_health
list_devices = devices_mod.list_devices


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_system_info(live_client):
    """Verify get_system_info returns version and hostname from the console."""
    result = await get_system_info(live_client)
    assert "version" in result, f"Expected 'version' in result, got keys: {list(result.keys())}"
    assert "hostname" in result, f"Expected 'hostname' in result, got keys: {list(result.keys())}"
    print(f"Console: {result['hostname']} v{result['version']}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_health(live_client):
    """Verify get_health returns a non-empty list including the 'wan' subsystem."""
    result = await get_health(live_client)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) > 0, "Health check returned empty list"
    subsystems = [h["subsystem"] for h in result]
    print(f"Subsystems: {subsystems}")
    assert "wan" in subsystems, f"Expected 'wan' in subsystems, got: {subsystems}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_list_devices(live_client):
    """Verify list_devices returns a list and print a brief summary."""
    result = await list_devices(live_client)
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    print(f"Found {len(result)} devices")
    for device in result[:3]:
        print(f"  {device['name']} ({device['model']}) - {device['state']}")
