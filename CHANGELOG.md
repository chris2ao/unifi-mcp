# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.2.1]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.2.1
[0.2.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.2.0
