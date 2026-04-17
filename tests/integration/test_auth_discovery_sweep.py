"""Auth discovery sweep integration tests.

Runs every parameterless read-only tool against a live UniFi console and logs
results via the DiscoveryRegistry. After the sweep, prints a summary of which
endpoints succeeded and which required session auth (401/403).

Gated behind INTEGRATION=1 to avoid accidental live-console hits from `pytest`.

Run with:
    INTEGRATION=1 UNIFI_HOST=... UNIFI_API_KEY=... \\
        uv run pytest tests/integration/test_auth_discovery_sweep.py -v -s

Tools that require arguments (get_camera, get_device, etc.) are excluded from
the sweep by design. PRODUCT_UNAVAILABLE stubs (Protect events, PTZ, reboot,
recording-mode) are also excluded since they don't make HTTP calls.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("INTEGRATION") != "1",
    reason="Integration sweep requires INTEGRATION=1 and a reachable UniFi console. "
           "Run with: INTEGRATION=1 uv run pytest tests/integration/ -v -s",
)

# Tool imports are intentionally forward-referenced. Modules are built by a
# parallel agent. The READONLY_TOOLS list below is populated as each module
# is committed. Add new entries here without changing the test logic.
#
# Pattern for each entry:
#   ("module.function_name", callable)
#
# Modules are imported lazily inside _build_tools() so that a missing module
# skips only that entry rather than failing the entire collection phase.

def _build_tools() -> list[tuple[str, object]]:
    """Build the READONLY_TOOLS list, skipping any modules not yet available."""
    tools = []

    # --- network.system ---
    try:
        from unifi_mcp.tools.network import system
        tools.append(("system.get_system_info", system.get_system_info))
        tools.append(("system.get_health", system.get_health))
        if hasattr(system, "get_alarms"):
            tools.append(("system.get_alarms", system.get_alarms))
        if hasattr(system, "get_events"):
            tools.append(("system.get_events", system.get_events))
    except ImportError:
        pass

    # --- network.devices ---
    try:
        from unifi_mcp.tools.network import devices
        tools.append(("devices.list_devices", devices.list_devices))
    except ImportError:
        pass

    # --- network.clients ---
    try:
        from unifi_mcp.tools.network import clients
        tools.append(("clients.list_clients", clients.list_clients))
    except ImportError:
        pass

    # --- network.networks ---
    try:
        from unifi_mcp.tools.network import networks
        tools.append(("networks.list_networks", networks.list_networks))
    except ImportError:
        pass

    # --- network.firewall ---
    try:
        from unifi_mcp.tools.network import firewall
        if hasattr(firewall, "list_firewall_rules"):
            tools.append(("firewall.list_firewall_rules", firewall.list_firewall_rules))
        if hasattr(firewall, "list_firewall_groups"):
            tools.append(("firewall.list_firewall_groups", firewall.list_firewall_groups))
    except ImportError:
        pass

    # --- network.wifi ---
    try:
        from unifi_mcp.tools.network import wifi
        if hasattr(wifi, "list_wlans"):
            tools.append(("wifi.list_wlans", wifi.list_wlans))
    except ImportError:
        pass

    # --- network.zbf (Zone-Based Firewall) ---
    try:
        from unifi_mcp.tools.network import zbf
        if hasattr(zbf, "list_zbf_zones"):
            tools.append(("zbf.list_zbf_zones", zbf.list_zbf_zones))
        if hasattr(zbf, "list_zbf_policies"):
            tools.append(("zbf.list_zbf_policies", zbf.list_zbf_policies))
    except ImportError:
        pass

    # --- network.topology ---
    try:
        from unifi_mcp.tools.network import topology
        if hasattr(topology, "get_topology"):
            tools.append(("topology.get_topology", topology.get_topology))
    except ImportError:
        pass

    # --- network.traffic_flows ---
    try:
        from unifi_mcp.tools.network import traffic_flows
        if hasattr(traffic_flows, "list_traffic_flows"):
            tools.append(("traffic_flows.list_traffic_flows", traffic_flows.list_traffic_flows))
    except ImportError:
        pass

    # --- protect.cameras ---
    try:
        from unifi_mcp.tools.protect import cameras
        tools.append(("protect.list_cameras", cameras.list_cameras))
        tools.append(("protect.list_liveviews", cameras.list_liveviews))
    except ImportError:
        pass
    except AttributeError:
        # list_liveviews may not exist; only list_cameras is required.
        pass

    # --- protect.devices ---
    try:
        from unifi_mcp.tools.protect import devices as protect_devices
        tools.append(("protect.list_nvrs", protect_devices.list_nvrs))
        tools.append(("protect.get_nvr_stats", protect_devices.get_nvr_stats))
    except ImportError:
        pass

    # Note: get_camera, get_camera_snapshot, update_camera_name, set_camera_recording_mode,
    # ptz_camera, reboot_camera, list_motion_events, list_smart_detections are excluded because:
    # - get_camera, get_camera_snapshot, update_camera_name, set_camera_recording_mode, etc.
    #   require specific parameters (camera_id, name, etc.) that the sweep harness cannot provide.
    # - PRODUCT_UNAVAILABLE stubs (list_motion_events, list_smart_detections) don't make HTTP
    #   calls and are not useful for auth discovery.

    return tools


READONLY_TOOLS = _build_tools()


# Parametrize only if there are tools available. When all modules are missing
# (pre-implementation), produce a single placeholder that skips immediately.
_params = READONLY_TOOLS if READONLY_TOOLS else [("(no tools loaded)", None)]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("name,tool_fn", _params)
async def test_readonly_endpoint_with_api_key(live_client, name, tool_fn):
    """Test each read-only endpoint with API key auth. Logs result to discovery registry."""
    if tool_fn is None:
        pytest.skip("No tool modules available yet (built by parallel agent)")

    try:
        result = await tool_fn(live_client)
        print(f"OK: {name}")
        assert result is not None, f"Tool {name} returned None"
    except Exception as e:
        print(f"FAIL: {name} - {e}")
        raise


@pytest.mark.integration
@pytest.mark.asyncio
async def test_print_discovery_report(live_client):
    """Print the auth discovery summary after the sweep.

    Run this test last (pytest orders parametrized tests before non-parametrized
    in the same file, so this naturally runs after the sweep).
    """
    report = live_client.discovery.get_summary()

    print(f"\n=== Auth Discovery Summary ===")
    print(f"Total requests: {report['total_requests']}")
    print(f"Successful: {report['successful']}")
    print(f"Auth failures: {report['auth_failures']}")
    print(f"Success rate: {report['success_rate']}%")

    failures = live_client.discovery.get_auth_failures()
    if failures:
        print(f"\n=== Endpoints requiring session auth ===")
        for f in failures:
            print(f"  {f['method']} {f['endpoint']} -> {f['status_code']}")
    else:
        print("\nAll tested endpoints accepted API key auth.")

    full_report = live_client.discovery.get_report()
    if full_report:
        print(f"\n=== All tested endpoints ===")
        for entry in full_report:
            status_label = "OK" if 200 <= entry["status_code"] < 400 else f"ERR({entry['status_code']})"
            print(f"  [{status_label}] {entry['method']} {entry['endpoint']}")
