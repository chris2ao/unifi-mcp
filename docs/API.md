# API Reference

Complete tool reference for chris2ao-unifi-mcp. All tools are async and accept a `UnifiClient` instance as their first parameter (injected automatically by the server).

Tools marked with **(Tier 2)** use the preview-confirm pattern: call with `confirm=False` (default) to preview, then `confirm=True` to execute.

---

## Utility Tools (Always Available)

These 7 tools are registered at server startup, before any product loader is called. `load_cloud_tools` is added to this set when the Site Manager (cloud) tools ship in a later release.

### load_network_tools

Load UniFi Network tools, optionally only some groups.

- **Parameters:** `groups: list[str] | None = None`
- **Groups:** `core` (system, devices, clients, networks, WiFi, topology, backups, hotspot, port profiles), `security` (firewall, zone-based firewall, DNS policies, traffic matching lists, MAC ACL, RADIUS, port forwarding, traffic rules, QoS, VPN, webhooks) and `insights` (DPI, traffic flows, dashboard summary, speed tests, WAN status).
- **Group syntax:** names may be passed bare (`"core"`), with the product prefix (`"network:core"`), or as `"all"`. Omit `groups` to use `UNIFI_TOOL_GROUPS`, or to load every group when that is unset.
- **Incremental:** calling again with more groups registers only the new tools; reloading a loaded group is a no-op. An unknown group returns an `Unknown ... Available: ...` message and registers nothing.
- **Returns:** `str` (summary of registered tools, or message if product not detected)

### load_protect_tools

Load UniFi Protect tools, optionally only some groups.

- **Parameters:** `groups: list[str] | None = None`
- **Groups:** `cameras` (cameras, camera controls, live views and viewers, live events), `devices` (NVRs, accessories) and `security` (Alarm Manager).
- **Behavior:** same group syntax and incremental loading as `load_network_tools`.
- **Returns:** `str`

### load_access_tools

Load UniFi Access tools (door control, NFC/PIN credentials, visitor passes, access policies).

- **Parameters:** None
- **Returns:** `str`

### list_tool_groups

List the tool groups each product loader can register: group name, modules, tool count, and whether it is loaded. Does not contact the console.

- **Parameters:** None
- **Returns:** `dict` with the per-product group report, `default_groups` (the `UNIFI_TOOL_GROUPS` value, or `"all"`), and a `usage` hint

### get_auth_report

Get the auth discovery report showing API key success/failure per endpoint.

- **Parameters:** None
- **Returns:** `dict` with keys: `summary`, `auth_failures`, `full_log`

### get_server_info

Get server status: package version, console, site, preview TTL, loaded products and groups, and console firmware drift.

- **Parameters:** None
- **Returns:** `dict` with keys: `server`, `version` (the installed package version), `console`, `site`, `preview_ttl_seconds`, `products` (loaded tools and groups per product), `console_versions` (Network and Protect versions the console reports, `null` when unknown), `verified_versions` (the versions this server was tested against: Network 10.6.106, Protect 7.2.105), `drift` (products whose major.minor differs from the verified version) and `drift_hint`. Version lookups are best effort and never fail the call.

### get_mutation_log

Get the audit log of confirmed Tier 2 changes made in this server session, oldest first.

- **Parameters:** None
- **Returns:** `list[dict]` with keys: `tool`, `params` (secret-looking values masked as `***`), result summary, UTC timestamp. In memory only; resets when the server restarts.

---

## Devices (16 tools)

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

Module: `tools/network/device_ops.py`

The official Integration API device tools. Device arguments accept the Integration API device UUID or a MAC address.

### get_device_statistics

Get latest live statistics for one adopted device (Integration API).

Use for health checks: uptime, CPU %, memory %, load averages, uplink tx/rx rate (bits per second) and per-radio retry %. `device` is the Integration device id or the MAC address.

- **Parameters:** `device: str`
- **Returns:** `dict`

### get_device_details_v1

Get Integration API details for one adopted device.

Returns features (switching, accessPoint), ports (state, speed, PoE), radios, firmware version and update flag, and provisioning timestamps. `device` is the Integration device id or the MAC address.

- **Parameters:** `device: str`
- **Returns:** `dict`

### list_pending_devices

List devices waiting to be adopted (Integration API, console-wide).

- **Parameters:** None
- **Returns:** `list[dict]`

### power_cycle_port **(Tier 2)**

Power cycle (PoE off then on) one switch port to reboot the device on it.

Use to recover a hung camera, AP or other PoE device. `device` is the switch's Integration id or MAC; `port_idx` is the 1-based port number. The powered device loses power and reboots. Requires confirm=True after previewing.

- **Parameters:** `device: str`, `port_idx: int`, `confirm: bool = False`
- **Returns:** `dict`

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

## Networks/VLANs (7 tools)

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

Delete a network. Requires confirm=True after previewing.

The preview lists resources that still reference the network.

- **Parameters:** `network_id: str`, `confirm: bool = False`
- **Returns:** `dict`


### get_dhcp_leases

Get active DHCP leases for a specific network.

- **Parameters:** `network_id: str`
- **Returns:** `list[dict]` with keys: mac, hostname, ip, name

### get_network_references

List what still references a network (devices, clients, WiFi, routes, NAT).

Use before deleting or changing a network. Accepts the Integration network id (UUID) or the legacy network id from list_networks. Output is grouped by resource type with counts and (up to 20) referencing ids.

- **Parameters:** `network_id: str`
- **Returns:** `dict`

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

## Zone-Based Firewall (15 tools)

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

### Official API tools and id types

Modules: `tools/network/zbf_official.py` and `tools/network/zbf_zones_official.py`.

The tools below use the official Integration API (`/firewall/policies`, `/firewall/zones`, spec 10.6.106). Policy ids from the Integration API are UUIDs and are **not** the same as the v2 `_id` values returned by `list_zbf_policies` (verified on Network 10.6.106: no overlap across 88 policies). Use `list_zbf_policies_v1` to get Integration ids; every tool below validates ids as UUIDs and returns a `VALIDATION_ERROR` naming the id type needed. Zone ids come from `list_zbf_zones`. Network ids passed to the zone tools may be Integration UUIDs or the legacy ids from `list_networks` (mapped by network name).

### get_zbf_policy

Get one zone-based firewall policy by Integration API id (UUID from list_zbf_policies_v1).

Returns action, source/destination zone and traffic filters, logging, schedule and origin. Do not pass v2 '_id' values from list_zbf_policies; they are a different id type.

- **Parameters:** `policy_id: str`
- **Returns:** `dict`

### list_zbf_policies_v1

List ZBF policies via the official API (all pages), with Integration UUID ids.

Use this to get the policy ids needed by get_zbf_policy, toggle_zbf_policy, set_zbf_policy_logging and reorder_zbf_policies. Optional source_zone_id and destination_zone_id (zone UUIDs from list_zbf_zones) narrow the result; filter is the official API filter expression passed through unchanged.

- **Parameters:** `source_zone_id: str | None = None`, `destination_zone_id: str | None = None`, `filter: str | None = None`
- **Returns:** `list[dict]`

### toggle_zbf_policy **(Tier 2)**

Enable or disable a ZBF policy by Integration UUID. Requires confirm=True after previewing.

The PATCH endpoint only accepts loggingEnabled, so this reads the policy and sends the merged body with PUT. Disabling a policy can open or close traffic paths between zones immediately.

- **Parameters:** `policy_id: str`, `enabled: bool`, `confirm: bool = False`
- **Returns:** `dict`

### set_zbf_policy_logging **(Tier 2)**

Turn syslog logging on or off for a ZBF policy (PATCH loggingEnabled). Requires confirm=True after previewing.

policy_id is the Integration UUID from list_zbf_policies_v1. Logging only affects syslog output, not which traffic is allowed.

- **Parameters:** `policy_id: str`, `logging_enabled: bool`, `confirm: bool = False`
- **Returns:** `dict`

### get_zbf_policy_order

Get the user-defined policy order for one source/destination zone pair.

Both ids are zone UUIDs from list_zbf_zones. Returns policy ids (UUIDs) in evaluation order, split into before_system_defined (evaluated ahead of the built-in policies) and after_system_defined.

- **Parameters:** `source_zone_id: str`, `destination_zone_id: str`
- **Returns:** `dict`

### reorder_zbf_policies **(Tier 2)**

Reorder user-defined ZBF policies for a zone pair. Requires confirm=True after previewing.

ordered_policy_ids is the complete desired order of policy UUIDs (from get_zbf_policy_order); it must contain exactly the current set. Without after_system_defined_ids the before/after-system-defined section sizes are kept; pass after_system_defined_ids to set that section explicitly (then ordered_policy_ids is the before-system-defined section).

- **Parameters:** `source_zone_id: str`, `destination_zone_id: str`, `ordered_policy_ids: list[str]`, `after_system_defined_ids: list[str] | None = None`, `confirm: bool = False`
- **Returns:** `dict`

### create_zbf_zone **(Tier 2)**

Create a custom firewall zone with name and network_ids (network UUIDs or list_networks ids; may be empty). Requires confirm=True after previewing.

- **Parameters:** `name: str`, `network_ids: list[str]`, `confirm: bool = False`
- **Returns:** `dict`

### update_zbf_zone **(Tier 2)**

Rename a zone and/or replace its network_ids (GET-merge-PUT). Requires confirm=True after previewing.

Omitted fields keep their current value. network_ids replaces the whole list. System-defined zones accept network changes only, not renames.

- **Parameters:** `zone_id: str`, `name: str | None = None`, `network_ids: list[str] | None = None`, `confirm: bool = False`
- **Returns:** `dict`

### delete_zbf_zone **(Tier 2)**

Delete a custom (user-defined) firewall zone by UUID. Requires confirm=True after previewing.

System-defined zones (Internal, External, Gateway, Vpn, Hotspot, Dmz) cannot be deleted. Policies and networks that reference the zone may be affected.

- **Parameters:** `zone_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## DNS Policies (5 tools)

Module: `tools/network/dns_policies.py`

Local DNS records and conditional forwarding through the official Integration API (`/dns/policies`). Supported types: A, AAAA, CNAME, MX, TXT, SRV and FORWARD_DOMAIN. Cache category: `dns`.

### list_dns_policies

List DNS policies (local DNS records and domain forwarders) on the gateway.

Optional ``type`` is one of A_RECORD, AAAA_RECORD, CNAME_RECORD, MX_RECORD, TXT_RECORD, SRV_RECORD, FORWARD_DOMAIN. Optional ``filter`` is an official filter expression such as ``domain.like('*.example.com')``; filterable properties: type, id, enabled, domain, ipv4Address, ipv6Address, targetDomain, mailServerDomain, text, serverDomain, ipAddress, ttlSeconds, priority, service, protocol, port, weight. Follows pagination.

- **Parameters:** `type: str | None = None`, `filter: str | None = None`
- **Returns:** `list[dict] | dict`

### get_dns_policy

Get one DNS policy by its UUID, including all type-specific fields and ttl.

- **Parameters:** `policy_id: str`
- **Returns:** `dict`

### create_dns_policy **(Tier 2)**

Create a DNS policy (local record or domain forwarder). Requires confirm=True after previewing.

Pass ``type`` plus only the fields for that type. A_RECORD: ipv4_address, ttl_seconds. AAAA_RECORD: ipv6_address, ttl_seconds. CNAME_RECORD: target_domain, ttl_seconds. MX_RECORD: mail_server_domain, priority. TXT_RECORD: text. SRV_RECORD: server_domain, service (e.g. '_ldap'), protocol (e.g. '_tcp'), port, priority, weight. FORWARD_DOMAIN: ip_address of the DNS server queries for the domain are forwarded to. ttl_seconds (A/AAAA up to 86400, CNAME up to 604800) defaults to 14400.

- **Parameters:** `type: str`, `domain: str`, `ipv4_address: str | None = None`, `ipv6_address: str | None = None`, `target_domain: str | None = None`, `mail_server_domain: str | None = None`, `text: str | None = None`, `server_domain: str | None = None`, `service: str | None = None`, `protocol: str | None = None`, `port: int | None = None`, `priority: int | None = None`, `weight: int | None = None`, `ip_address: str | None = None`, `ttl_seconds: int | None = None`, `enabled: bool = True`, `confirm: bool = False`
- **Returns:** `dict`

### update_dns_policy **(Tier 2)**

Update fields of an existing DNS policy. Requires confirm=True after previewing.

``updates`` holds only the fields to change, using API names (domain, ipv4Address, ttlSeconds, enabled, ...); snake_case such as ttl_seconds is accepted. The policy type cannot be changed. The current policy is read, merged with ``updates`` and the full body is sent, because PUT replaces the policy.

- **Parameters:** `policy_id: str`, `updates: dict`, `confirm: bool = False`
- **Returns:** `dict`

### delete_dns_policy **(Tier 2)**

Delete a DNS policy by UUID. Requires confirm=True after previewing.

- **Parameters:** `policy_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## Traffic Matching Lists (5 tools)

Module: `tools/network/traffic_matching_lists.py`

Reusable IP address and port lists for firewall policies, through the official Integration API (`/traffic-matching-lists`). Cache category: `zbf`.

### list_traffic_matching_lists

List traffic matching lists (reusable port or IP sets referenced by firewall policies).

Optional ``type`` filters to PORTS, IPV4_ADDRESSES or IPV6_ADDRESSES. Each result has id, name, type and items. Follows pagination.

- **Parameters:** `type: str | None = None`
- **Returns:** `list[dict] | dict`

### get_traffic_matching_list

Get one traffic matching list by UUID, including all its port or IP items.

- **Parameters:** `list_id: str`
- **Returns:** `dict`

### create_traffic_matching_list **(Tier 2)**

Create a traffic matching list. Requires confirm=True after previewing.

``type`` is PORTS, IPV4_ADDRESSES or IPV6_ADDRESSES. ``items`` is a non-empty list. Ports: 443, "8000-8100" (1-65535) or spec objects. IPv4: "192.0.2.5", "198.51.100.0/24", "10.0.0.10-10.0.0.20". IPv6: "2001:db8::1", "2001:db8:1::/64" (no ranges). Spec objects like {"type": "SUBNET", "value": "..."} are also accepted.

- **Parameters:** `name: str`, `type: str`, `items: list`, `confirm: bool = False`
- **Returns:** `dict`

### update_traffic_matching_list **(Tier 2)**

Update a traffic matching list's name and/or items. Requires confirm=True after previewing.

Pass ``name``, ``items`` or both. ``items`` REPLACES the whole item set (same shorthand as create_traffic_matching_list). The list type cannot be changed. The current list is read and the full body is sent, because PUT replaces the list.

- **Parameters:** `list_id: str`, `name: str | None = None`, `items: list | None = None`, `confirm: bool = False`
- **Returns:** `dict`

### delete_traffic_matching_list **(Tier 2)**

Delete a traffic matching list by UUID. Requires confirm=True after previewing.

- **Parameters:** `list_id: str`, `confirm: bool = False`
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

## Traffic Flows (6 tools)

Module: `tools/network/traffic_flows.py`

Uses the v2 query endpoint `POST /proxy/network/v2/api/site/{site}/traffic-flows` (verified on Network 10.6.106; GET is 405). Flows are large (10,000+ per hour) and come back unordered, so tools cap the window at 7 days, the page size at 500 and the scan at 5,000 flows, and report `truncated` when more existed. The console caps `total_matching` at 10,000. Every tool returns a dict envelope (`window_minutes`, `total_matching`, `returned`, `flows`), not a bare list. Group: `insights`.

### list_traffic_flows

List recent network traffic flows (per-connection records), sorted newest first.

The console returns flows unordered, so on a busy network this is the newest of a sample of up to `limit` matching flows, not guaranteed the newest overall.

Use to inspect what connections happened in the last `minutes` (1 to 10080, default 60). `limit` caps flows returned (1 to 500, default 50). Optional filters: direction (local|outgoing|incoming), protocol (TCP, UDP, ICMP...), action (allowed|blocked), risk (low|medium|high), search (free text over IPs, device names, domains, services). Each flow is compact with bytes_*, source and destination.

- **Parameters:** `minutes: int = 60`, `limit: int = 50`, `direction: str | None = None`, `protocol: str | None = None`, `action: str | None = None`, `risk: str | None = None`, `search: str | None = None`
- **Returns:** `dict`

### get_top_talkers

Rank top traffic talkers by bytes over the last `minutes` (default 60).

`by` groups by source (client IP), destination (remote IP), service (HTTPS, DNS...) or domain. Aggregates bytes_total client-side over up to `max_flows` sampled flows (100 to 5000, default 2000); the result reports flows_scanned and truncated so totals are a sample when truncated is true. `limit` is how many rows to return (1 to 100).

- **Parameters:** `minutes: int = 60`, `limit: int = 10`, `by: str = 'source'`, `max_flows: int = 2000`
- **Returns:** `dict`

### filter_flows_by_app

Find traffic flows for an application, service or domain by name.

`app_name` is a free-text search (for example "google", "netflix", "dns", "youtube.com") matched by the console against service, domains, and device names. Window `minutes` (1 to 10080, default 60); `limit` 1 to 500.

- **Parameters:** `app_name: str`, `minutes: int = 60`, `limit: int = 50`
- **Returns:** `dict`

### filter_flows_by_client

Find traffic flows to or from one client, by IP address or MAC address.

Provide `client_ip` (for example 10.0.0.11) and/or `client_mac`. Matches the client as source or destination, sorted newest first (a sample, since the console returns flows unordered). Window `minutes` (1 to 10080, default 60); `limit` 1 to 500.

- **Parameters:** `client_ip: str | None = None`, `client_mac: str | None = None`, `minutes: int = 60`, `limit: int = 50`
- **Returns:** `dict`

### get_blocked_flows

List flows the firewall or threat engine blocked, sorted newest first (a sample).

Use to see what was denied (policy blocks, IPS, ad blocking, content filtering). Window `minutes` (1 to 10080, default 60); `limit` 1 to 500.

- **Parameters:** `minutes: int = 60`, `limit: int = 50`
- **Returns:** `dict`

### get_flow_summary

Summarize traffic over the last `minutes` (1 to 10080, default 60).

Returns counts by action, risk, direction and protocol, the top services by flow count and bytes, and total bytes, computed over up to 2000 sampled flows (see flows_scanned and truncated). Use as a first look before drilling in with list_traffic_flows or get_top_talkers.

- **Parameters:** `minutes: int = 60`
- **Returns:** `dict`

---

## Insights (3 tools)

Module: `tools/network/insights.py`

Read-only health views built on the aggregated dashboard, speed test and load-balancing endpoints. Group: `insights`.

### get_dashboard_summary

Get a one-call health overview of the network (the UniFi dashboard, summarized).

Use for "how is my network doing". Covers the last ~24h: WiFi Doctor optimization status, ISP metrics, CyberSecure (IPS threats), most active clients and APs, top app ids, WAN latency/loss/throughput per uplink, upgradable device count, WiFi connection success per radio, and internet downtime plus latest speed test.

- **Parameters:** None
- **Returns:** `dict`

### get_speedtest_history

Get WAN speed test history, newest first, with an average summary.

`limit` caps results (1 to 200, default 20). `wan` filters to one uplink by network group name (WAN, WAN2; case-insensitive). `since_days` (1 to 3650) only returns tests from the last N days (server-side timestampFrom). A download of 0 Mbps means the test failed.

- **Parameters:** `limit: int = 20`, `wan: str | None = None`, `since_days: int | None = None`
- **Returns:** `dict`

### get_wan_status

Get the live state of each WAN uplink (ACTIVE, BACKUP, ...) with names and ids.

Combines load-balancing status (state per WAN network group) with the Integration API WAN list (name and id). Use to see which uplink carries traffic and which are standby or in another state.

- **Parameters:** None
- **Returns:** `dict`

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

## Webhooks (3 tools, PRODUCT_UNAVAILABLE stubs)

Module: `tools/network/webhooks.py`

Network 9.x moved webhook recipients to `/v2/api/site/{site}/notifications`, and on Network 10.6.106 that path returns 404 as well. The three tools stay registered and return the `PRODUCT_UNAVAILABLE` envelope without calling the console. `create_webhook` and `delete_webhook` accept `confirm` for signature compatibility and are marked `never_previews`, so `confirm=True` returns the explanation instead of a preview loop. Manage webhook recipients in the Network web UI.

### list_webhooks

List webhook recipients. Currently unavailable via the API.

- **Parameters:** None
- **Returns:** `dict`

### create_webhook **(Tier 2)**

Create a webhook recipient. Currently unavailable via the API.

- **Parameters:** `name: str`, `url: str`, `confirm: bool = False`
- **Returns:** `dict`

### delete_webhook **(Tier 2)**

Delete a webhook recipient. Currently unavailable via the API.

- **Parameters:** `webhook_id: str`, `confirm: bool = False`
- **Returns:** `dict`

---

## System (5 tools)

Module: `tools/network/system.py`

Network 10.6 serves events from the System Log (`POST /v2/api/site/{site}/system-log/all` and `/count`). The older `stat/event` and `stat/alarm` paths return 404 on 10.6.106, so events and alarms are both built on `system-log/all`.

### get_system_info

Get UniFi controller system information including version, hostname, and uptime.

- **Parameters:** None
- **Returns:** `dict`

### get_health

Get health status for all subsystems (WAN, WLAN, LAN, VPN).

- **Parameters:** None
- **Returns:** `list[dict]`

### get_alarms

Get recent alarms: HIGH and VERY_HIGH severity System Log events (threats blocked, WAN failover, outages).

Network 10.6 removed the legacy alarm list, so alarms are the high-severity System Log entries. hours: look-back window in hours (1 to 2160, default 168 = 7 days). limit: max alarms returned (1 to 1000), newest first. Each item has the same compact shape as get_events.

- **Parameters:** `hours: float = 168`, `limit: int = 50`
- **Returns:** `list[dict]`

### get_events

Get UniFi Network System Log events (client connects, threats, admin access, WAN, updates), newest first.

hours: look-back window in hours (1 to 2160). limit: page size and max events returned (1 to 1000). page: 0-based page for older events. categories: any of AUDIT, CLIENT_DEVICES, INTERNET_AND_WAN, POWER, SECURITY, SOFTWARE_UPDATES, UNIFI_DEVICES, UNIFI_ETHERNET_PORTS, UNKNOWN, VPN. severities: any of INFO, LOW, MEDIUM, WARNING, HIGH, VERY_HIGH. category: deprecated, "threats" equals categories=["SECURITY"] and "triggers" means all; ignored when categories is given. Returns a list of compact events: id, time (ISO 8601 UTC), category, subcategory, severity, key, event, type, title, message (rendered text) and target ({type, id, name, ip}). Use get_event_counts for totals in a window.

- **Parameters:** `limit: int = 50`, `hours: float = 24`, `categories: list[str] | None = None`, `severities: list[str] | None = None`, `page: int = 0`, `category: str | None = None`
- **Returns:** `list[dict]`

### get_event_counts

Count System Log events in a time window, grouped by category, event name and coarse type.

Use for a quick overview before paging through get_events. hours: look-back window (1 to 2160). Optional categories / severities filters take the same values as get_events. Returns {hours, time_from, time_to, total, by_category, by_event, by_type}, each map sorted by count descending. by_event keys match each event's `event` field in get_events (for example CLIENT_CONNECTED_WIRELESS), not its `key` field. by_type is a coarse AUDIT/GENERAL split and does not match the per-event `type` field.

- **Parameters:** `hours: float = 24`, `categories: list[str] | None = None`, `severities: list[str] | None = None`
- **Returns:** `dict`

---

## UniFi Protect (40 tools)

Module: `tools/protect/`. Register with `load_protect_tools`.

Protect tools run against the Integration API at `/proxy/protect/integration/v1/`, which accepts the same `X-API-Key` header as the Network surface. This is a different API than the legacy `/proxy/protect/api/` surface (which requires cookie auth and is out of scope).

Tested firmware: **Protect 7.2.105** (published spec 7.3.70). The Integration API on this firmware exposes cameras, PTZ, RTSPS streams, live views, viewers, accessories, Alarm Manager and two WebSocket event channels. It does not expose per-event queries (history), recording-mode control or camera reboot. The two tools that cannot execute (`set_camera_recording_mode`, `reboot_camera`) register as PRODUCT_UNAVAILABLE stubs so callers can discover them and route around them deliberately.

Protect groups: `cameras` (23 tools: cameras, camera controls, views, events), `devices` (8: NVRs, accessories) and `security` (9: Alarm Manager). Tier 2 tools use the preview-confirm flow described at the top of this file; Tier 1 tools run immediately.

### Error envelope: `PRODUCT_UNAVAILABLE`

Two tools in this surface return the following envelope when the required endpoint is not available on the connected firmware. Callers can branch on `result.get("error") is True` and `result.get("category") == "PRODUCT_UNAVAILABLE"` to handle these stubs without tripping over the actual error handlers used for network failures.

```json
{
  "error": true,
  "category": "PRODUCT_UNAVAILABLE",
  "message": "<specific probe results and pointer to the Protect UI>"
}
```

---

## Cameras (6 tools)

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
- **Note:** No confirm flag required (Tier 1). Live-verified against the G5 PTZ on Protect 7.2.105. See Camera controls below for the other camera writes.

### set_camera_recording_mode **(PRODUCT_UNAVAILABLE stub)**

Attempt to change a camera's recording mode.

- **Parameters:** `camera_id: str`, `mode: str` (`"always"` | `"motion"` | `"never"`), `confirm: bool = False`
- **Returns:** PRODUCT_UNAVAILABLE envelope
- **Why stubbed:** PATCH /cameras/{id} on Protect 7.2.105 has no recording-mode field. The spec (7.3.70) accepts only `name`, `osdSettings`, `ledSettings`, `lcdMessage`, `micVolume`, `videoMode`, `hdrType` and `smartDetectSettings`.
- **Future behavior:** When UniFi ships recording mode in the Integration API, the "no network call" unit test will fail and force a proper implementation with a Tier 2 confirm flow.
- **Future endpoint:** likely PATCH /cameras/{id} with `{"recordingSettings": {"mode": "..."}}` once the schema accepts it.

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
- **Why stubbed:** POST /cameras/{id}/reboot, POST /cameras/{id}/restart, PUT /cameras/{id}/reboot, and POST /nvrs/reboot all return 404 on Protect 7.2.105, and the spec 7.3.70 has no reboot endpoint for cameras or NVRs.

---

## Camera controls (7 tools)

Module: `tools/protect/camera_controls.py` (group `cameras`). Settings validation lives in `camera_settings_validation.py`. Cache category `protect_cameras`.

### ptz_camera **(Tier 1)**

Move a PTZ camera to a saved preset or start and stop a saved patrol. Free pan, tilt and zoom is not offered by the API.

- **Parameters:** `camera_id: str`, `action: str` (`"goto"` | `"patrol_start"` | `"patrol_stop"`), `slot: int | None = None`
- **Slots:** `goto` takes -1 (home) to 99; `patrol_start` takes 0-4; `patrol_stop` takes none.
- **Returns:** `dict` with `executed`, `action`, `camera_id`, `ptz_action`, `slot`, `response`. A camera whose model name does not contain "PTZ" returns a `VALIDATION_ERROR`. When the model is unknown the call is attempted and a console rejection is reported as not PTZ-capable. An unknown camera returns `NOT_FOUND`.
- **Endpoint:** POST /proxy/protect/integration/v1/cameras/{id}/ptz/goto/{slot}, /ptz/patrol/start/{slot}, /ptz/patrol/stop

### update_camera_settings **(Tier 2)**

Change camera settings. Pass only the keys to change.

- **Parameters:** `camera_id: str`, `settings: dict`, `confirm: bool = False`
- **Allowed keys:** `osdSettings`, `ledSettings`, `lcdMessage`, `micVolume` (1-100), `videoMode` (limited to the camera's feature flags, `homekit` excluded), `hdrType` (`auto` | `on` | `off`), `smartDetectSettings`. `name` is rejected (use `update_camera_name`). Unknown keys are rejected locally to avoid `AJV_PARSE_ERROR`.
- **Returns:** preview `dict` with `changes` (`current` and `proposed` per key); on confirm `{executed, action, camera_id, settings, response}`. An empty 200 body is reported as `executed: False`.
- **Endpoint:** PATCH /proxy/protect/integration/v1/cameras/{id}

### set_camera_led **(Tier 1)**

Turn the status LED on or off.

- **Parameters:** `camera_id: str`, `enabled: bool`
- **Returns:** `dict` with `executed`, `action`, `camera_id`, `enabled`, `response`
- **Endpoint:** PATCH /proxy/protect/integration/v1/cameras/{id} with `{"ledSettings": {"isEnabled": ...}}`

### disable_camera_mic_permanently **(Tier 2)**

PERMANENTLY disable a camera's microphone. Irreversible until the camera is factory reset.

- **Parameters:** `camera_id: str`, `confirm: bool = False`
- **Returns:** preview `dict`, then `{executed, action, camera_id, response}`
- **Endpoint:** POST /proxy/protect/integration/v1/cameras/{id}/disable-mic-permanently

### get_rtsps_streams **(Tier 1)**

List a camera's existing RTSPS stream URLs by quality.

- **Parameters:** `camera_id: str`, `reveal_urls: bool = False`
- **Returns:** `dict` with `camera_id`, `revealed`, `streams` (quality to URL, null when no stream exists). The token in each URL is masked at any depth unless `reveal_urls=True`. Revealed URLs are bearer credentials: anyone who can reach the console on port 7441 can watch the camera.
- **Endpoint:** GET /proxy/protect/integration/v1/cameras/{id}/rtsps-stream

### create_rtsps_stream **(Tier 2)**

Create RTSPS stream URLs.

- **Parameters:** `camera_id: str`, `qualities: list` (`high`, `medium`, `low`, `package`), `confirm: bool = False`
- **Returns:** preview `dict`, then `{executed, action, camera_id, qualities, response}` with masked URLs. The `package` quality requires a camera with a package camera.
- **Endpoint:** POST /proxy/protect/integration/v1/cameras/{id}/rtsps-stream with `{"qualities": [...]}`

### delete_rtsps_stream **(Tier 2)**

Delete RTSPS streams. Anything using the removed URLs stops working.

- **Parameters:** `camera_id: str`, `qualities: list`, `confirm: bool = False`
- **Returns:** preview `dict` with `impact`, then `{executed, action, camera_id, qualities, response}`
- **Endpoint:** DELETE /proxy/protect/integration/v1/cameras/{id}/rtsps-stream?qualities=a&qualities=b (repeated parameter, unverified against a console)

---

## Live views and viewers (6 tools)

Module: `tools/protect/views.py` (group `cameras`, all Tier 1). Cache categories `protect_liveviews` (shared with `list_liveviews`) and `protect_viewers`.

### get_liveview

- **Parameters:** `liveview_id: str`
- **Returns:** `dict` (id, name, layout, slots with cameras and cycle settings, flags), or `NOT_FOUND`
- **Endpoint:** GET /proxy/protect/integration/v1/liveviews/{id}

### create_liveview

- **Parameters:** `name: str`, `layout: int` (1-26, must equal `len(slots)`), `slots: list[dict]`, `is_global: bool = False`
- **Slots:** `{"cameras": [ids], "cycleMode": "time" | "motion", "cycleInterval": seconds}`; cycle mode defaults to `time` and interval to 10.
- **Returns:** `dict` with `executed`, `action`, `liveview`
- **Endpoint:** POST /proxy/protect/integration/v1/liveviews

### update_liveview

- **Parameters:** `liveview_id: str`, `updates: dict` (`name`, `isDefault`, `isGlobal`, `layout`, `slots`; snake_case aliases accepted)
- **Behavior:** changing `slots` alone sets `layout` to the new slot count; `layout` without `slots` is rejected. An empty 200 response is reported as `executed: False`.
- **Endpoint:** PATCH /proxy/protect/integration/v1/liveviews/{id}

### list_viewers

- **Parameters:** None
- **Returns:** `list[dict]` (id, name, state, MAC, stream limit, assigned live view id)
- **Endpoint:** GET /proxy/protect/integration/v1/viewers

### get_viewer

- **Parameters:** `viewer_id: str`
- **Returns:** `dict`, or `NOT_FOUND`
- **Endpoint:** GET /proxy/protect/integration/v1/viewers/{id}

### set_viewer_liveview

Assign a live view to a viewer (wall display). Pass `liveview_id=None` to clear the assignment.

- **Parameters:** `viewer_id: str`, `liveview_id: str | None`
- **Endpoint:** PATCH /proxy/protect/integration/v1/viewers/{id} with `{"liveview": ...}`

---

## Accessories (5 tools)

Module: `tools/protect/accessories.py` (group `devices`). Cache category `protect_devices`. One generic tool set covers `lights`, `sensors`, `chimes`, `sirens`, `relays`, `speakers`, `bridges`, `link-stations`, `alarm-hubs` and `fobs`. Secret-looking fields (tokens, passwords, PSKs, RTSPS URLs) are removed from output.

### list_protect_devices **(Tier 1)**

- **Parameters:** `kind: str`
- **Returns:** `list[dict]` of device records
- **Endpoint:** GET /proxy/protect/integration/v1/{kind}

### get_protect_device **(Tier 1)**

- **Parameters:** `kind: str`, `device_id: str`
- **Returns:** `dict`, or `NOT_FOUND`
- **Endpoint:** GET /proxy/protect/integration/v1/{kind}/{id}

### update_protect_device **(Tier 2)**

Update settings from a per-kind allow-list built from each kind's PATCH schema.

- **Parameters:** `kind: str`, `device_id: str`, `settings: dict`, `confirm: bool = False`
- **Returns:** preview `dict` with `current`, `proposed` and an optional `impact`; on confirm `{executed, action, response}`. An empty 200 is reported as `executed: False`.
- **Endpoint:** PATCH /proxy/protect/integration/v1/{kind}/{id}

### run_protect_device_action **(Tier 2)**

Run a physical action. Sirens are loud and relays can open gates or doors.

- **Parameters:** `kind: str`, `device_id: str`, `action: str`, `output_id: int | str | None = None`, `options: dict | None = None`, `confirm: bool = False`
- **Actions:** sirens `play` (`options.duration` 5, 10, 20 or 30 seconds), `stop`, `test-sound` (`options.volume` 1-100); speakers `test-sound` (`options.volume` 0-100); relays `activate` (needs `output_id`; `options.state` `on`/`off` is required, `options.pulseDuration` ms); alarm-hubs `trigger` (needs `output_id`; `options.enable` is required, `options.delay` and `options.duration` ms).
- **Toggle:** the console toggles a relay or alarm hub output when state or enable is omitted. Pass `options={"toggle": True}` to do that deliberately; it is removed from the request body.
- **output_id:** a non-negative integer (0 or 1) or numeric string, taken from relay `outputs[].id` or the alarm hub output keys.
- **Returns:** preview `dict` with `impact` and, for relays and alarm hubs, an `effect` line; on confirm `{executed, action, kind, device_id, device_action, response}`
- **Endpoint:** POST /proxy/protect/integration/v1/{kind}/{id}/{action}, or .../{kind}/{id}/outputs/{output_id}/{action}

### list_protect_users **(Tier 1)**

- **Parameters:** None
- **Returns:** `dict` with `users`, `ulp_users` (id, name, email, status, source) and `errors`. No tokens or credentials are returned.
- **Endpoint:** GET /proxy/protect/integration/v1/users and /ulp-users

---

## Alarm Manager (9 tools)

Module: `tools/protect/alarm.py` (group `security`). Cache category `protect_alarm`. Alarm endpoints are only available when the alarm manager is local.

### list_arm_profiles **(Tier 1)**

- **Parameters:** None
- **Returns:** `list[dict]` (id, name, automations, schedules, record_everything, activation_delay_ms, creator, created_at, updated_at)
- **Endpoint:** GET /proxy/protect/integration/v1/arm-profiles

### get_alarm_status **(Tier 1)**

- **Parameters:** None
- **Returns:** `dict` with `nvr_id`, `status` (`disabled` | `arming` | `armed` | `breach`), `arm_profile_id` (null on firmware that does not expose it, such as Protect 7.2.105), `armed_at`, `will_be_armed_at`, `breach_detected_at`, `breach_event_count`, `breach_trigger_event_id`, `breach_event_id`. Timestamps are epoch milliseconds. Returns `PRODUCT_UNAVAILABLE` when the NVR has no `armMode`.
- **Endpoint:** GET /proxy/protect/integration/v1/nvrs

### arm_alarm **(Tier 2)**

Arm using the active profile.

- **Parameters:** `confirm: bool = False`
- **Returns:** preview `dict` with `impact`, `current_status`, `active_profile_id`, `active_profile_name` and `available_profiles`; on confirm `{executed, action, response}`. When already armed or arming, `{executed: False, current_status, message}`.
- **Endpoint:** POST /proxy/protect/integration/v1/arm-profiles/enable

### disarm_alarm **(Tier 2)**

- **Parameters:** `confirm: bool = False`
- **Returns:** preview `dict` with `impact` and `current_status`; no-op `{executed: False}` when already disabled
- **Endpoint:** POST /proxy/protect/integration/v1/arm-profiles/disable

### set_active_arm_profile **(Tier 2)**

Select the active profile without arming.

- **Parameters:** `profile_id: str`, `confirm: bool = False`
- **Endpoint:** PATCH /proxy/protect/integration/v1/arm-profiles/settings with `{"armProfileId": ...}`

### create_arm_profile **(Tier 2)**

- **Parameters:** `name: str`, `automations: list[str] | None`, `schedules: list[dict] | None` (`{"start": cron, "end": cron}`), `record_everything: bool | None`, `activation_delay: int | None` (0, 60000, 300000 or 600000 ms), `confirm: bool = False`
- **Defaults:** no automations, no schedules, `record_everything=False`, `activation_delay=0` (the spec requires all five fields).
- **Endpoint:** POST /proxy/protect/integration/v1/arm-profiles

### update_arm_profile **(Tier 2)**

- **Parameters:** `profile_id: str`, `updates: dict` (`name`, `automations`, `schedules`, `recordEverything`, `activationDelay`; snake_case aliases accepted), `confirm: bool = False`
- **Returns:** an empty 200 is reported as `executed: False`
- **Endpoint:** PATCH /proxy/protect/integration/v1/arm-profiles/{id}

### delete_arm_profile **(Tier 2)**

Irreversible.

- **Parameters:** `profile_id: str`, `confirm: bool = False`
- **Endpoint:** DELETE /proxy/protect/integration/v1/arm-profiles/{id}

### trigger_alarm_webhook **(Tier 2)**

Fire an Alarm Manager webhook trigger. The id is a user-defined trigger string.

- **Parameters:** `webhook_id: str`, `confirm: bool = False`
- **Returns:** `{executed, action, webhook_id, response, note}`. The console answers 204 whether or not any alarm uses the id, so success means only that the trigger was sent.
- **Endpoint:** POST /proxy/protect/integration/v1/alarm-manager/webhook/{id}

---

## Events (4 tools)

Module: `tools/protect/events.py` (group `cameras`, all Tier 1). Protect has no REST event history, so these tools connect to the Protect Integration WebSocket (`/proxy/protect/integration/v1/subscribe/events` or `/subscribe/devices`) with the `X-API-Key` header, collect messages for a window, and close. TLS verification follows `UNIFI_VERIFY_SSL`. A connection failure returns a `CONNECTION_ERROR` dict that never contains the key. Camera names are looked up with GET /cameras; if that fails the result carries a `warning` and the stream continues.

### watch_protect_events

- **Parameters:** `seconds: int = 30` (cap 120), `event_types: list[str] | None` (for example `motion`, `smartDetectZone`, `smartDetectLine`, `ring`, `sensorMotion`), `camera_id: str | None`, `max_events: int = 100` (cap 500, counts messages)
- **Returns:** `dict` with `tool`, `window_seconds`, `messages_seen`, `count` (distinct events; add and update messages for one event id are merged), `events` (message_type, event_id, event_type, camera_id, camera_name, smart_detect_types, score, ISO start and end), `note`, and `capped` or `warning` when relevant

### list_motion_events

Live-window motion events.

- **Parameters:** `seconds: int = 30` (cap 120), `camera_id: str | None`
- **Returns:** same shape as `watch_protect_events`. The previous `limit` argument and `PRODUCT_UNAVAILABLE` stub behavior are gone.

### list_smart_detections

Live-window smart detections (person, vehicle, animal, package, face, licensePlate; audio detections such as `alrmSpeak` are passed through).

- **Parameters:** `seconds: int = 30` (cap 120), `detect_types: list[str] | None`, `camera_id: str | None`
- **Returns:** same shape as `watch_protect_events`

### watch_protect_device_updates

- **Parameters:** `seconds: int = 15` (cap 120), `max_messages: int = 100` (cap 500)
- **Returns:** `dict` with `tool`, `window_seconds`, `messages_seen`, `count`, `messages` (message_type `add` | `update` | `remove`, model_key, device_ids, name, state, changed_fields), `note`

---
