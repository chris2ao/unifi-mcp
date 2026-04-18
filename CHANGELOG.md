# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-04-18

### Fixed

- `forget_device` now uses the correct UniFi command name `delete-device` (was `delete`, which the controller silently ignored on Network 10.x; the operation appeared to succeed and the device stayed in the controller).
- `forget_device` now succeeds against offline devices. The previous implementation always posted to `/cmd/devmgr`, which requires the device to be reachable so the controller can send it an unadopt command. Offline devices produced a `meta.rc: ok` response with empty `data: []` and the device stayed in the controller (silent no-op). The tool now:
  - Probes the device's `state` via `/stat/device/<mac>` and routes to `/cmd/sitemgr` when the device is offline (matching the Web UI's "Forget" button behavior on offline devices).
  - Defensively retries on `/cmd/sitemgr` when `/cmd/devmgr` returns the silent-no-op pattern (`meta.rc: ok` paired with empty `data`), in case the state probe was stale.
  - Defaults to `/cmd/sitemgr` when the state probe cannot resolve the device record (e.g., device already partly removed).

### Changed

- `forget_device` response now includes three additional fields so callers can confirm which path executed:
  - `endpoint`: the UniFi path actually called (`/cmd/devmgr` or `/cmd/sitemgr`)
  - `device_state`: `online`, `offline`, or `unknown` (from the pre-flight probe)
  - `retried_on_sitemgr`: `True` if the devmgr call silently no-opped and the tool fell back to sitemgr

### Added

- `_probe_device_state` and `_is_silent_noop` private helpers in `unifi_mcp.tools.network.devices`. The latter detects UniFi's "I parsed your request but did nothing" response shape (`meta.rc: ok` with empty `data`), which is a generally useful pattern for any mutation tool.
- Four new tests covering online-routing, offline-routing, devmgr-silent-fallback, and unknown-state-default cases (`tests/unit/test_network_devices.py`).

### Notes

This release was driven by a real-world incident on 2026-04-18 where an offline US8P60 switch could not be removed from a UDM Pro / Network 10.2.105 controller via the MCP. The Web UI's "Forget" button worked because it routes through the site-level endpoint; the previous REST surface did not. No user action is required beyond upgrading.

## [0.2.1] - 2026-04-17

### Fixed

- **Dynamic tool loaders now emit `notifications/tools/list_changed`.** After calling `load_network_tools`, `load_protect_tools`, or `load_access_tools`, the MCP client would report success ("Registered N tools") but the newly registered tools remained invisible to the client for the rest of the session, so calls like `list_clients` failed and restarting the session did not help. FastMCP 3.x registers tools on the server at runtime but does not automatically notify the client that the tool list has changed, so Claude Code (and any other `listChanged`-aware MCP client) kept serving its stale initial tool list. The three loader tools now accept a `Context` parameter and call `await ctx.session.send_tool_list_changed()` after registration so clients refresh immediately. No user action is required beyond upgrading.
- `get_server_info` now reports the correct version (`0.2.1`) instead of the stale `0.1.0` string that was carried forward from pre-release development.

## [0.2.0] - 2026-04-17

### Added

- Initial public release.
- UniFi Network tools covering devices, clients, firewalls, WiFi, VPN, topology, traffic flows, port forwarding, QoS, hotspot, RADIUS, MAC ACL, zone-based firewall, backups, webhooks, and more.
- UniFi Protect Phase 2 tools: read-only camera, motion event, recording, and smart detection access, plus `update_camera_name` and three control-tool stubs.
- UniFi Access tool loader with installation probe (tools to be implemented in a later release).
- Auth discovery sweep with per-endpoint success/failure reporting via `get_auth_report`.
- Site UUID resolver, TTL response cache, and safety manager with preview/confirm flow for destructive operations.
- Lazy per-product tool loading to keep the initial tool list small.
- Claude Code plugin bundle with installation guide, setup instructions, and API reference.

[0.3.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.3.0
[0.2.1]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.2.1
[0.2.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.2.0
