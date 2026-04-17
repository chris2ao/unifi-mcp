# API Reference

Complete tool reference for chris2ao-unifi-mcp. All tools are async and accept a `UnifiClient` instance as their first parameter (injected automatically by the server).

Tools marked with **(Tier 2)** use the preview-confirm pattern: call with `confirm=False` (default) to preview, then `confirm=True` to execute.

---

## Utility Tools (Always Available)

These 5 tools are registered at server startup, before any product loader is called.

### load_network_tools

Load all UniFi Network management tools.

- **Parameters:** None
- **Returns:** `str` (summary of registered tools, or message if product not detected)

### load_protect_tools

Load UniFi Protect tools (cameras, motion events, recordings, smart detection).

- **Parameters:** None
- **Returns:** `str`

### load_access_tools

Load UniFi Access tools (door control, NFC/PIN credentials, visitor passes, access policies).

- **Parameters:** None
- **Returns:** `str`

### get_auth_report

Get the auth discovery report showing API key success/failure per endpoint.

- **Parameters:** None
- **Returns:** `dict` with keys: `summary`, `auth_failures`, `full_log`

### get_server_info

Get server status including loaded products and tool counts.

- **Parameters:** None
- **Returns:** `dict` with keys: `server`, `version`, `console`, `site`, `products`

---

## Devices (12 tools)

Module: `tools/network/devices.py`

### list_devices

List all network devices (APs, switches, gateways) with status and stats.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, mac, name, model, type, ip, version, upgradable, state, adopted, uptime, uptime_human, clients, tx_bytes, tx_human, rx_bytes, rx_human

### get_device

Get detailed information for a specific device by MAC address.

- **Parameters:** `mac: str`
- **Returns:** `dict` (same fields as list_devices)

### restart_device **(Tier 2)**

Restart a network device.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict` (preview or execution result)

### adopt_device **(Tier 2)**

Adopt a new device into the network.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict`

### forget_device **(Tier 2)**

Remove a device from the network.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict`

### locate_device

Toggle the locate LED on a device.

- **Parameters:** `mac: str`, `enabled: bool = True`
- **Returns:** `dict`

### rf_scan **(Tier 2)**

Trigger an RF environment scan on an AP. Briefly disrupts wireless service.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict`

### upgrade_firmware **(Tier 2)**

Upgrade device firmware to the latest version. Device will restart.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict`

### rename_device

Rename a device (cosmetic change).

- **Parameters:** `device_id: str`, `name: str`
- **Returns:** `dict`

### get_device_stats

Get detailed statistics for a device (CPU, memory, throughput).

- **Parameters:** `mac: str`
- **Returns:** `dict` with keys: mac, name, cpu_usage, mem_usage, uptime, uptime_human, clients, tx_bytes, tx_human, rx_bytes, rx_human

### get_device_ports

Get port status for a switch device.

- **Parameters:** `mac: str`
- **Returns:** `list[dict]` with keys: port, name, enabled, speed, is_uplink, poe_mode, poe_power

### get_device_uplinks

Get uplink information for a device.

- **Parameters:** `mac: str`
- **Returns:** `dict` with keys: mac, name, uplink_mac, uplink_device_name, type, speed

---

## Clients (8 tools)

Module: `tools/network/clients.py`

### list_clients

List all currently connected (active) clients.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, mac, hostname, ip, name, network, is_wired, is_guest, uptime, uptime_human, tx_bytes, tx_human, rx_bytes, rx_human, signal, satisfaction, blocked

### get_client

Get details for a specific client by MAC address.

- **Parameters:** `mac: str`
- **Returns:** `dict` (same fields as list_clients)

### block_client **(Tier 2)**

Block a client from the network.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict`

### unblock_client **(Tier 2)**

Unblock a previously blocked client.

- **Parameters:** `mac: str`, `confirm: bool = False`
- **Returns:** `dict`

### reconnect_client

Force a client to reconnect (kick and rejoin). Non-destructive.

- **Parameters:** `mac: str`
- **Returns:** `dict`

### set_client_alias

Set a friendly name (alias) for a client. Cosmetic change.

- **Parameters:** `client_id: str`, `name: str`
- **Returns:** `dict`

### list_all_clients

List all known clients (historical, including offline).

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, mac, hostname, name

### get_client_history

Get hourly usage history for a client.

- **Parameters:** `mac: str`
- **Returns:** `list[dict]` (raw hourly report data with rx_bytes, tx_bytes)

---

## Networks/VLANs (6 tools)

Module: `tools/network/networks.py`

### list_networks

List all configured networks/VLANs.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, purpose, subnet, vlan_enabled, vlan, dhcpd_enabled, dhcpd_start, dhcpd_stop, domain_name, networkgroup

### get_network

Get details for a specific network by ID.

- **Parameters:** `network_id: str`
- **Returns:** `dict` (same fields as list_networks)

### create_network **(Tier 2)**

Create a new network/VLAN.

- **Parameters:** `name: str`, `purpose: str = "corporate"`, `subnet: str = ""`, `vlan: int | None = None`, `dhcpd_enabled: bool = True`, `dhcpd_start: str = ""`, `dhcpd_stop: str = ""`, `domain_name: str = ""`, `confirm: bool = False`
- **Returns:** `dict`

### update_network **(Tier 2)**

Update an existing network.

- **Parameters:** `network_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_network **(Tier 2)**

Delete a network. Irreversible.

- **Parameters:** `network_id: str`, `confirm: bool = False`
- **Returns:** `dict`

### get_dhcp_leases

Get active DHCP leases for a specific network.

- **Parameters:** `network_id: str`
- **Returns:** `list[dict]` with keys: mac, hostname, ip, name

---

## Legacy Firewall (8 tools)

Module: `tools/network/firewall.py`

### list_firewall_rules

List all legacy firewall rules.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, enabled, action, protocol, src_address, dst_address, dst_port, rule_index, ruleset

### create_firewall_rule **(Tier 2)**

Create a new firewall rule.

- **Parameters:** `name: str`, `action: str`, `protocol: str = "all"`, `ruleset: str = "LAN_IN"`, `src_address: str = ""`, `dst_address: str = ""`, `src_port: str = ""`, `dst_port: str = ""`, `rule_index: int = 2000`, `enabled: bool = True`, `confirm: bool = False`
- **Returns:** `dict`

### update_firewall_rule **(Tier 2)**

Update an existing firewall rule.

- **Parameters:** `rule_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_firewall_rule **(Tier 2)**

Delete a firewall rule.

- **Parameters:** `rule_id: str`, `confirm: bool = False`
- **Returns:** `dict`

### reorder_firewall_rules **(Tier 2)**

Change a firewall rule's position by updating its rule_index.

- **Parameters:** `rule_id: str`, `new_index: int`, `confirm: bool = False`
- **Returns:** `dict`

### list_firewall_groups

List all firewall groups (address groups and port groups).

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, group_type, group_members

### create_firewall_group **(Tier 2)**

Create a new firewall group.

- **Parameters:** `name: str`, `group_type: str`, `members: list[str]`, `confirm: bool = False`
- **Returns:** `dict`

### delete_firewall_group **(Tier 2)**

Delete a firewall group.

- **Parameters:** `group_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## Zone-Based Firewall (6 tools)

Module: `tools/network/zbf.py`

Requires UniFi Network Application 9.0+. Reference: enuno/unifi-mcp-server.

### list_zbf_zones

List all ZBF firewall zones.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, description, networks

### get_zbf_zone

Get details for a specific ZBF zone.

- **Parameters:** `zone_id: str`
- **Returns:** `dict` (same fields as list_zbf_zones)

### list_zbf_policies

List all ZBF firewall policies.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, source_zone_id, destination_zone_id, action, protocol, enabled, index

### create_zbf_policy **(Tier 2)**

Create a new ZBF firewall policy.

- **Parameters:** `name: str`, `source_zone_id: str`, `destination_zone_id: str`, `action: str = "ALLOW"`, `protocol: str = "all"`, `enabled: bool = True`, `confirm: bool = False`
- **Returns:** `dict`

### update_zbf_policy **(Tier 2)**

Update an existing ZBF policy.

- **Parameters:** `policy_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_zbf_policy **(Tier 2)**

Delete a ZBF firewall policy.

- **Parameters:** `policy_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## WiFi/SSID (6 tools)

Module: `tools/network/wifi.py`

### list_wlans

List all configured wireless networks (SSIDs).

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, enabled, security, wlan_band, networkconf_id, hide_ssid, is_guest, num_sta

### create_wlan **(Tier 2)**

Create a new wireless network.

- **Parameters:** `name: str`, `security: str = "wpapsk"`, `passphrase: str = ""`, `wlan_band: str = "both"`, `networkconf_id: str = ""`, `hide_ssid: bool = False`, `guest_mode: bool = False`, `confirm: bool = False`
- **Returns:** `dict` (passphrase is excluded from preview for security)

### update_wlan **(Tier 2)**

Update an existing wireless network.

- **Parameters:** `wlan_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_wlan **(Tier 2)**

Delete a wireless network. Irreversible.

- **Parameters:** `wlan_id: str`, `confirm: bool = False`
- **Returns:** `dict`

### get_wlan_stats

Get per-SSID client statistics (aggregated from active clients).

- **Parameters:** None
- **Returns:** `dict` keyed by SSID name, each with: client_count, tx_bytes, rx_bytes

### toggle_wlan **(Tier 2)**

Enable or disable a wireless network.

- **Parameters:** `wlan_id: str`, `enabled: bool`, `confirm: bool = False`
- **Returns:** `dict`

---

## VPN (2 tools)

Module: `tools/network/vpn.py`

### list_vpn_servers

List all VPN server configurations.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, purpose, enabled

### list_vpn_clients

List all VPN client configurations.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, purpose, enabled

---

## Port Forwarding (4 tools)

Module: `tools/network/port_forwarding.py`

### list_port_forwards

List all port forwarding rules.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, fwd_ip, fwd_port, dst_port, proto, enabled

### create_port_forward **(Tier 2)**

Create a new port forwarding rule.

- **Parameters:** `name: str`, `fwd_ip: str`, `fwd_port: str`, `dst_port: str`, `proto: str = "tcp"`, `enabled: bool = True`, `confirm: bool = False`
- **Returns:** `dict`

### update_port_forward **(Tier 2)**

Update an existing port forwarding rule.

- **Parameters:** `rule_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_port_forward **(Tier 2)**

Delete a port forwarding rule.

- **Parameters:** `rule_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## DPI (2 tools)

Module: `tools/network/dpi.py`

### get_dpi_stats

Get site-wide Deep Packet Inspection statistics (application and category breakdown).

- **Parameters:** None
- **Returns:** `list[dict]` (raw DPI data)

### get_dpi_by_app

Get DPI traffic breakdown for a specific client by MAC address.

- **Parameters:** `mac: str`
- **Returns:** `list[dict]` (per-app traffic data)

---

## Hotspot (2 tools)

Module: `tools/network/hotspot.py`

### list_vouchers

List all guest network vouchers.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, code, quota, duration, used, note

### create_voucher

Create guest network vouchers. Non-destructive (Tier 1).

- **Parameters:** `expire_minutes: int = 1440`, `quota: int = 1`, `count: int = 1`, `note: str = ""`
- **Returns:** `dict`

---

## MAC ACL (3 tools)

Module: `tools/network/mac_acl.py`

### list_mac_filter

List all MAC ACL filter rules.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, action, mac_addresses

### add_mac_filter

Add a new MAC ACL filter rule.

- **Parameters:** `name: str`, `action: str`, `mac_addresses: list[str]`
- **Returns:** `dict`

### delete_mac_filter

Delete a MAC ACL filter rule.

- **Parameters:** `rule_id: str`
- **Returns:** `dict`

---

## QoS (2 tools)

Module: `tools/network/qos.py`

Reference: enuno/unifi-mcp-server (ProAV QoS).

### list_qos_rules

List all QoS (Quality of Service) rules.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, enabled, action, rate_limit_up, rate_limit_down

### get_bandwidth_profiles

Get bandwidth/QoS profiles with full details.

- **Parameters:** None
- **Returns:** `list[dict]` (raw QoS rule data)

---

## Topology (3 tools)

Module: `tools/network/topology.py`

Reference: enuno/unifi-mcp-server.

### get_topology

Build a network topology graph from device uplink relationships.

- **Parameters:** None
- **Returns:** `dict` with keys: `nodes` (list of devices), `edges` (list of uplink connections with from_mac, to_mac, type, speed)

### get_uplink_tree

Build a hierarchical uplink tree with the gateway as root.

- **Parameters:** None
- **Returns:** `dict` (recursive tree with mac, name, type, model, children)

### get_port_table

Get the port table for a specific device (switches, gateways).

- **Parameters:** `mac: str`
- **Returns:** `list[dict]` with keys: port, name, speed, is_uplink

---

## Traffic Flows (4 tools)

Module: `tools/network/traffic_flows.py`

Reference: enuno/unifi-mcp-server. Uses the Integration API.

### list_traffic_flows

List recent traffic flows with source, destination, protocol, and app info.

- **Parameters:** `limit: int = 50`
- **Returns:** `list[dict]` (flow records)

### get_top_talkers

Get top traffic flows sorted by total bytes (sent + received).

- **Parameters:** `limit: int = 10`
- **Returns:** `list[dict]` (sorted flow records)

### filter_flows_by_app

Filter traffic flows by application name (case-insensitive match).

- **Parameters:** `app_name: str`
- **Returns:** `list[dict]`

### filter_flows_by_client

Filter traffic flows by source or destination IP address.

- **Parameters:** `client_ip: str`
- **Returns:** `list[dict]`

---

## RADIUS (4 tools)

Module: `tools/network/radius.py`

Reference: enuno/unifi-mcp-server.

### list_radius_profiles

List all RADIUS server profiles.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, auth_servers, acct_servers

### create_radius_profile **(Tier 2)**

Create a new RADIUS profile.

- **Parameters:** `name: str`, `auth_servers: list[dict]`, `acct_servers: list[dict] | None = None`, `confirm: bool = False`
- **Returns:** `dict`

### update_radius_profile **(Tier 2)**

Update an existing RADIUS profile.

- **Parameters:** `profile_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_radius_profile **(Tier 2)**

Delete a RADIUS profile.

- **Parameters:** `profile_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## Port Profiles (4 tools)

Module: `tools/network/port_profiles.py`

Reference: enuno/unifi-mcp-server. Includes PoE mode support.

### list_port_profiles

List all switch port profiles.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, native_networkconf_id, poe_mode, forward

### create_port_profile **(Tier 2)**

Create a new port profile.

- **Parameters:** `name: str`, `native_networkconf_id: str = ""`, `poe_mode: str = "auto"`, `forward: str = "all"`, `confirm: bool = False`
- **Returns:** `dict`

### update_port_profile **(Tier 2)**

Update an existing port profile.

- **Parameters:** `profile_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_port_profile **(Tier 2)**

Delete a port profile.

- **Parameters:** `profile_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## Backups (3 tools)

Module: `tools/network/backups.py`

Reference: enuno/unifi-mcp-server.

### list_backups

List all available controller backups.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: filename, time, size

### create_backup

Create a new controller backup. Non-destructive (Tier 1).

- **Parameters:** None
- **Returns:** `dict`

### restore_backup **(Tier 2)**

Restore a controller backup. Replaces ALL settings and restarts the controller.

- **Parameters:** `filename: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## Webhooks (3 tools)

Module: `tools/network/webhooks.py`

Reference: enuno/unifi-mcp-server.

### list_webhooks

List all configured webhooks.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: id, name, url, enabled

### create_webhook

Create a new webhook.

- **Parameters:** `name: str`, `url: str`, `enabled: bool = True`
- **Returns:** `dict`

### delete_webhook

Delete a webhook.

- **Parameters:** `webhook_id: str`
- **Returns:** `dict`

---

## System (4 tools)

Module: `tools/network/system.py`

### get_system_info

Get UniFi controller system information including version, hostname, and uptime.

- **Parameters:** None
- **Returns:** `dict` with keys: hostname, name, version, build, timezone, uptime, uptime_human, update_available, autobackup

### get_health

Get health status for all subsystems (WAN, WLAN, LAN, VPN).

- **Parameters:** None
- **Returns:** `list[dict]` (per-subsystem health data)

### get_alarms

Get active alarms from the UniFi controller.

- **Parameters:** None
- **Returns:** `list[dict]` (alarm records)

### get_events

Get recent events from the UniFi controller.

- **Parameters:** `limit: int = 50`
- **Returns:** `list[dict]` (event records)

---

## UniFi Protect (Phase 2, 12 tools)

Module: `tools/protect/`. Register with `load_protect_tools`.

Protect tools run against the Integration API at `/proxy/protect/integration/v1/`, which accepts the same `X-API-Key` header as the Network surface. This is a different API than the legacy `/proxy/protect/api/` surface (which requires cookie auth and is out of scope).

Tested firmware: **Protect 7.0.104**. The Integration API on this firmware exposes a limited surface: cameras (list/get/snapshot/rename), liveviews (list), NVRs (list/get). It does not expose per-event queries, recording-mode control, PTZ, or camera reboot. The five tools that cannot execute on this firmware register as PRODUCT_UNAVAILABLE stubs (see below) so callers can discover them and route around them deliberately.

### Error envelope: `PRODUCT_UNAVAILABLE`

Five tools in this surface return the following envelope when the required endpoint is not available on the connected firmware. Callers can branch on `result.get("error") is True` and `result.get("category") == "PRODUCT_UNAVAILABLE"` to handle these stubs without tripping over the actual error handlers used for network failures.

```json
{
  "error": true,
  "category": "PRODUCT_UNAVAILABLE",
  "message": "<specific probe results and pointer to the Protect UI>"
}
```

---

## Cameras (7 tools)

Module: `tools/protect/cameras.py`

### list_cameras

List all cameras registered in Protect.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: `id`, `name`, `mac`, `modelKey`, `state`, `isMicEnabled`, `videoMode`, `hdrType`, `smart_detect_types` (list from featureFlags), `has_hdr`, `has_mic`, `has_speaker`
- **Cache:** `protect_cameras`, TTL 15s
- **Endpoint:** GET /proxy/protect/integration/v1/cameras

### get_camera

Get the full Protect record for a single camera.

- **Parameters:** `camera_id: str`
- **Returns:** `dict` (full Protect camera record, including full featureFlags and smartDetectSettings)
- **Cache:** `protect_cameras`, TTL 15s
- **Endpoint:** GET /proxy/protect/integration/v1/cameras/{id}

### get_camera_snapshot

Fetch a live JPEG snapshot from a camera. The image is base64-encoded in the response.

- **Parameters:** `camera_id: str`
- **Returns:** `dict` with keys: `camera_id`, `content_type`, `size_bytes`, `image_base64`
- **Note:** Decoded images are typically 500 KB to 2 MB; base64 encoding adds roughly 33%, so responses can reach 2.5 MB. Use this tool only when image inspection is required, as large responses consume context window.
- **Endpoint:** GET /proxy/protect/integration/v1/cameras/{id}/snapshot (returns `image/jpeg` binary, wrapped by `UnifiClient.get_binary`)

### list_liveviews

List all configured Protect liveviews.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: `id`, `name`, `is_default`, `is_global`, `layout`, `slot_count`
- **Cache:** `protect_liveviews`, TTL 60s
- **Endpoint:** GET /proxy/protect/integration/v1/liveviews

### update_camera_name **(Tier 1)**

Rename a camera. Cosmetic change, no service disruption.

- **Parameters:** `camera_id: str`, `name: str`
- **Returns:** `dict` with keys: `executed: True`, `action: "update_camera_name"`, `camera_id`, `name` (the updated name as returned by the API)
- **Side effect:** Invalidates the `protect_cameras` cache.
- **Endpoint:** PATCH /proxy/protect/integration/v1/cameras/{id} with body `{"name": "..."}`
- **Note:** No confirm flag required (Tier 1). Live-verified against the G5 PTZ on Protect 7.0.104. This is the only Tier 1 mutation available in the Protect surface on this firmware.

### set_camera_recording_mode **(PRODUCT_UNAVAILABLE stub)**

Attempt to change a camera's recording mode.

- **Parameters:** `camera_id: str`, `mode: str` (`"always"` | `"motion"` | `"never"`), `confirm: bool = False`
- **Returns:** PRODUCT_UNAVAILABLE envelope
- **Why stubbed:** PATCH /cameras/{id} on Protect 7.0.104 rejects every recording-related property shape (`mode`, `recording`, `recordingMode`, `recordingSettings.mode`, `settings.recordingMode`) with `AJV_PARSE_ERROR: must NOT have additional properties`. The strict JSON Schema on this firmware only accepts fields visible in the GET response, none of which relate to recording mode.
- **Future behavior:** When UniFi ships recording mode in the Integration API, the "no network call" unit test will fail and force a proper implementation with a Tier 2 confirm flow.
- **Future endpoint:** likely PATCH /cameras/{id} with `{"recordingSettings": {"mode": "..."}}` once the schema accepts it.

### ptz_camera **(PRODUCT_UNAVAILABLE stub)**

Attempt PTZ movement (pan, tilt, zoom) or preset recall on a camera.

- **Parameters:** `camera_id: str`, `pan: float | None`, `tilt: float | None`, `zoom: float | None`, `preset_id: str | None`, `confirm: bool = False`
- **Returns:** PRODUCT_UNAVAILABLE envelope
- **Why stubbed:** All PTZ probe paths return 404 on Protect 7.0.104: `/cameras/{id}/ptz`, `/cameras/{id}/ptz/position`, `/cameras/{id}/ptz/presets`, `/cameras/{id}/goto`, `/cameras/{id}/patrol`, `/cameras/{id}/pan`, `/cameras/{id}/tilt`, `/cameras/{id}/zoom`, `/cameras/{id}/move`. PATCH `activePatrolSlot` is also rejected by the schema.

---

## NVRs and Devices (3 tools)

Module: `tools/protect/devices.py`

### list_nvrs

List all NVRs registered in Protect.

- **Parameters:** None
- **Returns:** `list[dict]` (always a list, even when Protect returns a single NVR object). Keys: `id`, `name`, `model_key`, `version`, `doorbell_settings`
- **Cache:** `protect_nvrs`, TTL 60s
- **Endpoint:** GET /proxy/protect/integration/v1/nvrs

### get_nvr_stats

Get the full NVR record including storage and system stats.

- **Parameters:** None
- **Returns:** `dict` (full raw NVR record including storage, system stats, doorbell settings)
- **Cache:** `protect_nvrs`, TTL 15s
- **Endpoint:** GET /proxy/protect/integration/v1/nvrs

### reboot_camera **(PRODUCT_UNAVAILABLE stub)**

Attempt to reboot a camera via the Integration API.

- **Parameters:** `camera_id: str`, `confirm: bool = False`
- **Returns:** PRODUCT_UNAVAILABLE envelope
- **Why stubbed:** POST /cameras/{id}/reboot, POST /cameras/{id}/restart, PUT /cameras/{id}/reboot, and POST /nvrs/reboot all return 404 on Protect 7.0.104.

---

## Events (2 tools)

Module: `tools/protect/events.py`

### list_motion_events **(PRODUCT_UNAVAILABLE stub)**

Attempt to fetch motion events from Protect.

- **Parameters:** `camera_id: str | None`, `limit: int = 50`
- **Returns:** `[PRODUCT_UNAVAILABLE_envelope]` (single-element list containing the error envelope)
- **Why stubbed:** GET /proxy/protect/integration/v1/events returns 404 on Protect 7.0.104 via API key.

### list_smart_detections **(PRODUCT_UNAVAILABLE stub)**

Attempt to fetch smart detection events (person, vehicle, animal, package) from Protect.

- **Parameters:** `camera_id: str | None`, `limit: int = 50`
- **Returns:** `[PRODUCT_UNAVAILABLE_envelope]` (single-element list containing the error envelope)
- **Why stubbed:** Same endpoint as `list_motion_events`; returns 404 on Protect 7.0.104 via API key.

---
