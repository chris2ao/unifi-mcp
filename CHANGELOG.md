# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-10-04

Network insights, the remaining official Network endpoints, and an optional Site Manager (cloud) tool set. Network goes from 122 tools to 157, and 9 read-only cloud tools are added behind a new `load_cloud_tools` loader (8 always-loaded tools, 214 in total with everything loaded). Network OpenAPI coverage rises from 46.6% to 78.1% (57 of 73) and Site Manager coverage from 0% to 64.3% (9 of 14). Tested on UniFi Network 10.6.106 and UniFi Protect 7.2.105. The cloud tools were verified with mocked tests only.

### Added

- Routing (group `insights`, module `routing`, all Tier 1): `get_routing_table`, `list_static_routes` (reports `route_type`: nexthop-route, interface-route or blackhole), `list_traffic_routes`, `list_nat_rules`.
- Site insights (group `insights`, module `site_insights`, all Tier 1): `list_content_filters`, `list_neighbor_aps`, `get_site_traffic_history`, `list_vpn_connections`, `list_scheduled_tasks`, `list_dynamic_dns`, `get_site_settings`. These use internal or legacy endpoints and fail soft with an error dict naming the endpoint.
- Clients: `list_recent_clients` (timestamped client history, Tier 1), `get_client_v1` (official API, by UUID or MAC, Tier 1), `authorize_guest` and `unauthorize_guest` (Tier 2, guest portal bypass with optional time, data and rate limits).
- Hotspot: `list_vouchers_v1`, `get_voucher` (Tier 1), `delete_voucher` and `delete_vouchers` (Tier 2; `delete_vouchers` requires a filter and previews the matching vouchers).
- MAC ACL: `get_acl_rule_order` (Tier 1) and `reorder_acl_rules` (Tier 2).
- Lookups (group `core`, module `lookups`, all Tier 1, 14 tools): `list_wans`, `list_site_to_site_tunnels`, `list_device_tags`, `search_dpi_applications`, `list_dpi_categories`, `list_countries`, `list_switch_stacks`, `get_switch_stack`, `list_lags`, `get_lag`, `list_mc_lag_domains`, `get_mc_lag_domain`, `list_radius_profiles_v1`, `list_vpn_servers_v1`.
- Site Manager cloud tools (package `unifi_mcp.cloud`, tools in `tools/cloud`, all Tier 1): `list_cloud_hosts`, `get_cloud_host`, `list_cloud_sites`, `list_cloud_devices`, `get_isp_metrics`, `query_isp_metrics`, `list_sdwan_configs`, `get_sdwan_config`, `get_sdwan_status`.
- `load_cloud_tools`, the eighth always-loaded tool. It registers the cloud tools on demand and needs `UNIFI_CLOUD_API_KEY` (a unifi.ui.com key, separate from `UNIFI_API_KEY`). `UNIFI_CLOUD_BASE_URL` is optional and must be https on `ui.com`.
- Test fixtures for the new tools, including `tests/fixtures/cloud/`, and a test that calls the error path of list-returning tools through a FastMCP client.

### Changed

- `UNIFI_CLOUD_API_KEY` is read as a `SecretStr` and never appears in reprs or errors. Cloud 429 responses raise `CloudRateLimitError` (category `CONNECTION_ERROR`) with `rate_limited: true` and `retry_after_seconds`.
- `list_vouchers_v1`, `search_dpi_applications`, `list_countries`, `list_cloud_devices` and `get_isp_metrics` are annotated `list[dict] | dict` so a validation error is delivered as the error dict instead of failing output schema validation.
- Tier 2 map: `authorize_guest`, `unauthorize_guest` (cache category `clients`), `delete_voucher`, `delete_vouchers` (`hotspot`) and `reorder_acl_rules` (`mac_acl`) were added to the legacy map in `safety.py`.
- `get_cloud_host` returns `NOT_FOUND` unless the returned host id matches the requested id.
- `unauthorize_guest` returns `executed: false` with a message for a guest that is not authorized, and the `authorize_guest` preview adds an `impact` line when the guest is already authorized.
- `delete_vouchers` previews cap counting at 5000 and report `count_capped`. A filter with no matches returns `matched: 0` instead of a preview.
- Tests that used a real console address now use `192.0.2.1`.
- Tests that import `unifi_mcp.server` use a shared session fixture in `tests/conftest.py` that supplies placeholder `UNIFI_HOST` and `UNIFI_API_KEY` values, so the suite passes in CI where neither is set.

### Fixed

- HTTP 429 from the console is now retried. UniFi Protect's Integration API allows 10 requests per second and answers bursts with `429` and `Retry-After: 1` (measured on Protect 7.2.105), which made back-to-back Protect calls fail with a generic `CONNECTION_ERROR` and could make `load_protect_tools` report "not installed". `UnifiClient` now retries up to 3 times, honoring `Retry-After` capped at 5 seconds (exponential backoff when the header is missing or not numeric), then raises the new `RATE_LIMITED` error category. A rate-limited product probe now tells the caller to retry instead of claiming the product is missing.
- Cloud id validation accepted `.`, which httpx normalizes away, so `get_cloud_host(".")` returned the first console on the account. Ids must now start with a letter or digit.
- `get_client_v1`, `authorize_guest` and `unauthorize_guest` looked up a client by MAC with a filtered list and used the first row without checking it. The MAC is now verified, so a firmware that ignores the filter cannot cause the wrong guest to be authorized or disconnected.
- The `delete_voucher` preview read the voucher through a 30 second cache and could miss a redemption. It now reads live.
- Cloud timestamp validation requires an RFC3339 time with an offset (date-only and offset-less values are rejected locally).
- Cloud pagination logs a warning when it stops at the 20 page limit with more data pending.
- In-place list mutation was replaced with new objects in `list_recent_clients`, `search_dpi_applications`, `list_vpn_connections` and cloud pagination.

### Security

- `get_site_settings`, `list_dynamic_dns` and `list_vpn_connections` now also mask fields named like `community` (SNMP community strings), `signature` (for example `paypal_signature`), `private`, `certificate` and `configuration` (inline VPN configs), and `pem`, `cert` and `ca`, in addition to pass, secret, key, token, psk and `x_` names.
- Neighbor AP SSIDs are stripped of control characters and capped at 64 characters, and the docstring marks them as untrusted text from outside the network.
- `delete_vouchers` rejects an empty filter so it cannot delete every voucher, and the guest and voucher previews perform read-only lookups only.

### Notes

- Migration: no breaking changes to existing tools. `load_cloud_tools` adds one always-loaded tool, so the startup count is 8. The cloud tools do nothing unless `UNIFI_CLOUD_API_KEY` is set.
- Routing and site insight tools return empty lists on the test console for features that are not configured (static and traffic routes, NAT, DDNS, VPN, WireGuard), so their shapes come from tolerant formatting rather than live data. The legacy `rest/account` endpoint is deliberately not exposed because it holds `x_password`.
- `get_site_traffic_history` issues a read-only report query by POST. `list_neighbor_aps` sorts and filters on `signal` (dBm); the `rssi` field on the test console is a positive quality value.
- The official filter `name.like()` is case-sensitive and prefix-only, so `search_dpi_applications` and `list_countries` page the catalog (cached for an hour) and match substrings client-side. `clients/history` ignores `limit`, so `list_recent_clients` applies it client-side.
- Deferred review items: response size caps or summaries for `get_isp_metrics` and long `get_site_traffic_history` windows, moving the shared insight helpers into a common module, an allowlist for the `list_vpn_connections` `details` field, mapping cloud 429 responses to the new `RATE_LIMITED` category (the local client already uses it), and splitting `clients.py` (now over 400 lines).
- Site Manager connector proxy endpoints (`/v1/connector/consoles/{id}/*`) are not implemented.

## [0.7.0] - 2026-10-04

UniFi Protect expansion: PTZ presets and patrols, camera settings, RTSPS streams, Alarm Manager, live views and viewers, accessory devices, and live event streams. Protect goes from 11 tools to 40. Tested on UniFi Protect 7.2.105 (spec 7.3.70) and UniFi Network 10.6.106.

### Added

- Camera controls (group `cameras`, module `camera_controls`): `ptz_camera` (Tier 1; actions `goto` a preset slot with -1 as home, `patrol_start` slot 0-4, `patrol_stop`), `update_camera_settings` (Tier 2; OSD, LED, LCD message, mic volume 1-100, video mode, HDR, smart detect settings, validated against the spec allow-list and the camera's feature flags), `set_camera_led` (Tier 1), `disable_camera_mic_permanently` (Tier 2, irreversible).
- RTSPS streams: `get_rtsps_streams` (Tier 1, URLs masked unless `reveal_urls=True`), `create_rtsps_stream` (Tier 2), `delete_rtsps_stream` (Tier 2). Qualities: high, medium, low, package.
- Alarm Manager (new Protect group `security`, module `alarm`): `list_arm_profiles` and `get_alarm_status` (Tier 1); `arm_alarm`, `disarm_alarm`, `set_active_arm_profile`, `create_arm_profile`, `update_arm_profile`, `delete_arm_profile` and `trigger_alarm_webhook` (all Tier 2, cache category `protect_alarm`). Arm and disarm previews show the current status and active profile and return a no-op result when the alarm is already in the target state.
- Live views and viewers (group `cameras`, module `views`, all Tier 1): `get_liveview`, `create_liveview`, `update_liveview`, `list_viewers`, `get_viewer`, `set_viewer_liveview` (pass `liveview_id=None` to clear).
- Accessory devices (group `devices`, module `accessories`): `list_protect_devices`, `get_protect_device` and `list_protect_users` (Tier 1), `update_protect_device` and `run_protect_device_action` (Tier 2, cache category `protect_devices`). One generic tool set covers lights, sensors, chimes, sirens, relays, speakers, bridges, link stations, alarm hubs and fobs. Secret-looking fields (tokens, passwords, RTSPS URLs) are removed from device output.
- Live events over the Protect WebSocket (group `cameras`, module `events`, all Tier 1): `watch_protect_events`, `watch_protect_device_updates`, and live-window versions of `list_motion_events` and `list_smart_detections`. Connections use the `X-API-Key` header, follow `UNIFI_VERIFY_SSL`, and never include the key in error messages.
- Test fixtures for every new tool group in `tests/fixtures/protect/` (sanitized ids, MACs and hosts).

### Changed

- `ptz_camera` is no longer a `PRODUCT_UNAVAILABLE` stub. Its signature changed from `(pan, tilt, zoom, preset_id, confirm)` to `(camera_id, action, slot)`, and it is Tier 1 with no `confirm` parameter. Free pan, tilt and zoom is not offered by the API.
- `list_motion_events` and `list_smart_detections` are real but have no history. Protect has no REST event endpoint, so they listen on the live WebSocket for `seconds` (default 30, max 120) and return only events that occur in that window. The `limit` argument is gone, and both return a dict `{tool, window_seconds, messages_seen, count, events, note}` instead of a single-element stub list. `count` is distinct events: the add and update messages for one event id are merged, and `messages_seen` keeps the raw message volume.
- `run_protect_device_action` takes an extra optional `options` dict (siren duration and test volume, speaker volume, relay state and pulse duration, alarm hub enable, delay and duration) before `confirm`. `output_id` accepts an integer (0, 1) or a numeric string.
- `list_protect_users` returns a dict (`users`, `ulp_users`, `errors`).
- `get_alarm_status` reports `arm_profile_id` as null on firmware whose `armMode` has no `armProfileId` (Protect 7.2.105), and returns `PRODUCT_UNAVAILABLE` when the NVR exposes no `armMode` at all.
- `load_protect_tools` now has three groups: `cameras`, `devices` and `security`.
- `websockets` dependency range is now `>=14,<17` (the events tools use the `additional_headers` API).
- Protect OpenAPI coverage rises from 10.8% to 40.5% (30 of 74 operations).

### Fixed

- Relay `activate` and alarm hub `trigger` toggle the output when no state is given. `options.state` (relays) and `options.enable` (alarm hubs) are now required; toggling must be requested explicitly with `options={"toggle": True}`. Previews carry an `effect` line such as `turn output 0 ON for 500 ms` or `TOGGLE output 0 (current state unknown)`.
- `output_id` rejected integers copied from `list_protect_devices` (FastMCP failed validation on `0`) and accepted non-numeric ids. It is now validated as a non-negative integer.
- Siren `test-sound` now accepts `options.volume` (1-100), and siren play durations are validated in seconds rather than milliseconds.
- `get_protect_device` and the `update_protect_device` preview return a `NOT_FOUND` dict for an unknown device id instead of raising.
- `update_liveview` sets `layout` from the slot count when only `slots` is given, and rejects `layout` without `slots`.
- Camera setting validation: `micVolume` is 1-100 and `videoMode` excludes `homekit`, matching the PATCH schema. PTZ checks use the model name only and attempt the call when the model is unknown.
- Alarm helpers accept a `{"data": {...}}` wrapped NVR, and ids are matched with `fullmatch` so a trailing newline is rejected.
- RTSPS masking now covers nested and wrapped responses and the `delete_rtsps_stream` response.
- The stale legacy Tier 2 entry for `ptz_camera` was removed from `safety.py`.

### Security

- RTSPS URLs carry bearer tokens. They are masked in every response except `get_rtsps_streams(reveal_urls=True)`, whose docstring now warns that revealed URLs grant live video access.
- Arm and disarm previews expose the real alarm state so the user approves an accurate action, and `trigger_alarm_webhook` reports that a successful response does not confirm any alarm matched.

### Removed

- The `ptz_camera` stub signature `(pan, tilt, zoom, preset_id, confirm)` and the `PRODUCT_UNAVAILABLE` stub behavior of `list_motion_events` and `list_smart_detections`.

### Notes

- Still `PRODUCT_UNAVAILABLE` stubs: `set_camera_recording_mode` (no recording-mode field in the Integration API) and `reboot_camera` (no reboot endpoint).
- `get_alarm_status` is the tool name for the arm state (the plan document called it `get_arm_status`).
- Live checks on Protect 7.2.105 were read-only. Write paths (PTZ, settings, RTSPS create and delete, arm profiles, accessory actions) are covered by mocked tests only. The repeated `qualities=a&qualities=b` query format for `delete_rtsps_stream` is unverified against a console.
- Deferred review items: a short preview TTL or nonce for `arm_alarm` and `disarm_alarm`, an operator opt-in for `reveal_urls`, email redaction in `list_protect_users`, and replacing `get_all_pages` with `get` on Protect list endpoints (offset and limit are ignored on the tested console).

## [0.6.0] - 2026-10-04

Network official API tools, working traffic flows and insights on Network 10.6, server infrastructure (auto-discovered tool modules, tool groups, firmware drift), and OpenAPI spec tooling. This release also carries the Network 10.6 regression fixes and server hardening that were prepared as v0.5.1 and were never tagged separately.

### Added

- Tool groups. `load_network_tools` and `load_protect_tools` take an optional `groups` argument (network: `core`, `security`, `insights`; protect: `cameras`, `devices`). `"all"` and the `network:core` prefix form are accepted, and repeated calls are incremental: only the new tools register. Unknown groups return an `Unknown ... Available: ...` message.
- `list_tool_groups` (always loaded): groups, modules, tool counts and loaded state per product. The server now starts with 7 always-loaded tools.
- `UNIFI_TOOL_GROUPS` environment variable (for example `network:core,network:security,protect:cameras`). Unset loads every group; a product that is not mentioned loads all of its groups. Invalid entries fail at startup.
- `get_server_info` reports `console_versions`, `verified_versions`, `drift` and `drift_hint`, so a console firmware that differs from the tested versions (Network 10.6.106, Protect 7.2.105) is visible. Lookups are best effort and never fail the call.
- Traffic flows (rewritten on the 10.6 query endpoint): `get_blocked_flows` and `get_flow_summary` (counts by action, risk, direction and protocol, top services, and total bytes over a sample of up to 2000 flows).
- Insights (group `insights`): `get_dashboard_summary`, `get_speedtest_history`, `get_wan_status`.
- DNS policies (group `security`): `list_dns_policies`, `get_dns_policy`, `create_dns_policy` (Tier 2), `update_dns_policy` (Tier 2), `delete_dns_policy` (Tier 2). Types: A, AAAA, CNAME, MX, TXT, SRV, FORWARD_DOMAIN. New cache category `dns`.
- Traffic matching lists (group `security`): `list_traffic_matching_lists`, `get_traffic_matching_list`, `create_traffic_matching_list` (Tier 2), `update_traffic_matching_list` (Tier 2), `delete_traffic_matching_list` (Tier 2).
- Official zone-based firewall tools (group `security`): `get_zbf_policy`, `list_zbf_policies_v1`, `get_zbf_policy_order`, `toggle_zbf_policy` (Tier 2), `set_zbf_policy_logging` (Tier 2), `reorder_zbf_policies` (Tier 2), `create_zbf_zone` (Tier 2), `update_zbf_zone` (Tier 2), `delete_zbf_zone` (Tier 2).
- Device tools on the Integration API (group `core`): `get_device_statistics`, `get_device_details_v1`, `list_pending_devices`, `power_cycle_port` (Tier 2, category `devices`, previews the connected device and warns when PoE is down).
- `get_network_references`: what still references a network (devices, clients, WiFi, routes, NAT), accepting the legacy id or the Integration UUID.
- `get_event_counts`: System Log event totals grouped by category, event and type.
- `get_mutation_log` and an in-memory audit log of confirmed Tier 2 changes (secret-looking params masked). `UNIFI_PREVIEW_TTL_SECONDS` (default 600) sets how long a preview stays valid.
- `UnifiClient.get_all_pages` for Integration API `offset`/`limit` pagination with `filter` support.
- `scripts/spec_diff.py`, `scripts/spec_coverage.py`, vendored OpenAPI specs in `docs/specs/` (Network 10.6.106, Protect 7.3.70, Site Manager 1.0.0) and `docs/SPEC_MAINTENANCE.md`. `spec_diff.py` compares request bodies (including polymorphic subtypes), 2xx response schemas, parameters and limits; the console fetch honors `UNIFI_VERIFY_SSL`, refuses plain http and never follows redirects.
- `scripts/gen_tool_docs.py` generates `docs/TOOLS.md` (every tool with group, tier and description). CI runs it with `--check` and fails on a stale file. It refuses to run when tracked tool modules have unstaged edits.
- `websockets>=13` dependency.

### Changed

- Tool modules are auto-discovered: any module under `tools/<product>/` that exports `TOOLS` is loaded, with module-level `GROUP` and `TIER2_TOOLS` declarations. Module `TIER2_TOOLS` entries are merged into the `SafetyManager`; the legacy map in `safety.py` is kept (keyed by module) so existing tools stay Tier 2. A module that fails to import is skipped with a message on stderr instead of breaking the server.
- Preview-then-confirm is enforced by the server: a `confirm=True` call without a matching recent preview returns `PREVIEW_REQUIRED`. Previews are single use.
- `get_events` and `get_alarms` read the System Log on Network 10.6 (`system-log/all`). `get_events` gains `hours`, `categories`, `severities` and `page`; `get_alarms` gains `hours`. The legacy `category` argument still works (`threats` maps to the SECURITY category).
- Traffic flow tools return dict envelopes (`window_minutes`, `total_matching`, `returned`, `flows`) instead of the old `PRODUCT_UNAVAILABLE` list. `filter_flows_by_client` takes `client_ip` and/or `client_mac`. Results are a sample sorted newest first, because the console returns flows unordered. All pages of one scan share one time window.
- `delete_network` previews list the resources that still reference the network.
- `get_server_info` reports the installed package version (it was hardcoded).
- Protect stub messages name Protect 7.2.105 and spec 7.3.70.
- `list_webhooks`, `create_webhook` and `delete_webhook` are `PRODUCT_UNAVAILABLE` stubs: the notifications endpoint returns 404 on Network 10.6.106.
- Tested firmware is now UniFi Network 10.6.106 and UniFi Protect 7.2.105.

### Fixed

- `update_dns_policy` ignores response fields the policy type does not accept, so a field added by newer firmware cannot make every update fail.
- `delete_dns_policy` and `delete_traffic_matching_list` previews read the record, show what will be deleted, and return `NOT_FOUND` for an unknown id.
- `create_zbf_zone` and `update_zbf_zone` accept the legacy network ids from `list_networks` (mapped to Integration UUIDs by network name) and give a network-specific error for bad ids.
- `power_cycle_port` rejects ports with PoE disabled and warns when the port reports PoE state DOWN.
- Dashboard summaries skip unexpected response shapes instead of raising.

### Removed

- `ptz_camera` stub. The published Protect spec has PTZ endpoints, so a stub that claims PTZ is unavailable was wrong; PTZ support is planned for a later release.
- The README troubleshooting entry saying traffic flows are unavailable.

### Security

- `spec_diff.py` no longer sends the console API key over plain http, no longer ignores `UNIFI_VERIFY_SSL`, refuses redirects, and validates the console-reported spec version before using it in a file name.
- Vendored specs are published upstream content; example CIDRs in the Site Manager spec are not home-network data.

### Notes

- Integration API policy ids are UUIDs and are not the v2 `_id` values returned by `list_zbf_policies`. Use `list_zbf_policies_v1` for ids accepted by the official ZBF tools.
- `toggle_zbf_policy` uses GET then PUT because the PATCH schema (10.6.106) only accepts `loggingEnabled`. The write paths of the new tools were verified with previews and unit tests; confirmed writes were not run against a live console.
- Official-endpoint coverage from `scripts/spec_coverage.py`: Network 46.6% (34 of 73 operations), Protect 10.8% (8 of 74). Site Manager has no tools in this release (0 of 14). Coverage matches by path only, not HTTP method.
- Known limits: `reorder_zbf_policies` splits the list using the current before/after section sizes; if another admin moves policies between preview and confirm, preview again. `toggle_zbf_policy` does not yet refuse system-defined policies in the preview, and the console rejects the change.
- Upgrade: no configuration changes are required. Callers of `filter_flows_by_client` or the traffic flow tools must handle dict results instead of lists. Callers of `ptz_camera` get a missing-tool error.

## [0.5.0] - 2026-06-14

### Added

- Timestamped client history: `get_client_history` accepts `start` and `end` (epoch ms) and an `interval` (`hourly` or `daily`), and client records surface wired tx/rx byte counters so wired clients report real volume.

## [0.4.1] - 2026-06-13

### Fixed

- `list_port_forwards` now surfaces the forward target IP. The controller stores it in the `fwd` field (not `fwd_ip`) on UniFi Network 9.x, so a correctly-configured rule previously reported `fwd_ip: ""` and looked broken. Reads now prefer `fwd` and fall back to `fwd_ip`. (#5)
- `update_port_forward` no longer silently no-ops. The `/rest/portforward/{id}` PUT ignores a partial body (returns HTTP 200 with an empty `data` array but persists nothing). The tool now GETs the existing rule, merges the requested `updates` onto the full object, and PUTs the complete rule. (#5)
- `update_port_forward` now reports an empty `data` array as `executed: false` with an explanatory error instead of `executed: true`, so a non-persisting write is no longer indistinguishable from success. A missing rule id returns `executed: false` with a "not found" error. (#5)

### Added

- `update_port_forward` accepts the forward target as either `fwd` or `fwd_ip` in `updates`; both normalize to the controller's `fwd` field.
- `create_port_forward` gains an optional `pfwd_interface` parameter to bind a rule to a specific WAN interface on dual-WAN setups. `list_port_forwards` now includes `pfwd_interface` in its output. (#5)

## [0.4.0] - 2026-04-27

### Added

- `traffic_rules` tools (six total): `list_traffic_rules`, `get_traffic_rule`, `create_traffic_rule`, `update_traffic_rule`, `delete_traffic_rule`, `toggle_traffic_rule`. Wraps the UniFi v2 endpoint `/proxy/network/v2/api/site/{site}/trafficrules`. The create/update tools accept the full rule body as a free-form dict because the schema is rich and version-dependent; callers should fetch a similar existing rule via `list_traffic_rules` to discover the schema before constructing a new one.
- `tests/fixtures/traffic_rules.json` and `tests/unit/test_network_traffic_rules.py` covering the new tools (13 tests, all preview/confirmed paths plus the "not found" branch on `get_traffic_rule`).

### Fixed

- `auth.client._request` now tolerates an empty 2xx response body, treating it as an empty success dict. UniFi's v2 `DELETE /trafficrules/<id>` returns 200 with no Content-Type header and an empty body; previously this raised `UNEXPECTED_RESPONSE` and surfaced as a delete failure even though the rule was successfully removed.

### Changed

- Bumped `.claude-plugin/plugin.json` version from `0.3.1` to `0.4.0` to match `pyproject.toml`.

### Schema notes (UniFi v2 trafficrules)

Discovered while building these tools and worth documenting for callers:

- The rule label is `description`, not `name`. UniFi silently drops `name` on create.
- There is **no** `ports` field. Traffic Rules cannot filter by destination port: they match by `matching_target` (INTERNET / DOMAIN / IP / REGION / APP_CATEGORY / INTERNAL). For port-specific rules, use ZBF firewall policies (`/v2/api/site/{site}/firewall-policies`) instead.
- `target_devices` does not support an `exclude` flag. UniFi normalizes any `{"exclude": true}` field away on persist, so you cannot express "all devices on this network EXCEPT this client" in a single rule.
- `GET /trafficrules/{id}` returns 405. `get_traffic_rule` and `toggle_traffic_rule` fetch the collection and filter locally as a workaround.

## [0.3.1] - 2026-04-26

### Fixed

- `marketplace.json` plugin source path now uses `"./"` instead of `"."`. The bare `"."` form fails Claude Code marketplace schema validation with `Invalid schema: plugins.0.source: Invalid input`, so `/plugin marketplace add https://github.com/chris2ao/unifi-mcp.git` would refuse to load the catalog. The official Claude Code marketplace docs only document `"./"` or explicit subpaths for relative sources. Thanks to [@erikankrom](https://github.com/erikankrom) for catching this and submitting [#3](https://github.com/chris2ao/unifi-mcp/pull/3).

### Changed

- Bumped `.claude-plugin/plugin.json` version from `0.2.0` to `0.3.1` to match `pyproject.toml` (it had drifted out of sync since the v0.3.0 release).

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

[0.8.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.8.0
[0.7.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.7.0
[0.6.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.6.0
[0.5.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.5.0
[0.4.1]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.4.1
[0.4.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.4.0
[0.3.1]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.3.1
[0.3.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.3.0
[0.2.1]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.2.1
[0.2.0]: https://github.com/chris2ao/unifi-mcp/releases/tag/v0.2.0
