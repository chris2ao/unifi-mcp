# unifi-mcp v0.10.0: UniFi Network 11 upgrade plan

Date: 2026-11-12. Tracking: CLAUD-889. Branch: `release/v0.10.0`.

## Baseline

- Repo: v0.9.0 (`361a14a`), verified against Network 10.6.106 and Protect 7.2.105, vendored specs Network 10.6.106, Protect 7.3.70, Site Manager 1.0.0.
- Console (read-only probe): UDM Pro, UniFi OS 6.0.17, Network 11.0.99, Protect 7.3.74. Network 11 was installed on the day of this plan (statistics migration timestamp).
- Published by Ubiquiti: Network API 11.0.97 (same operations as the console's 11.0.99 spec), Protect API 7.4.96 (newer than the installed 7.3.74), Site Manager 1.0.0 (unchanged).
- Tests: 1553 passed, 97.55% line coverage. Live read sweep: 77 of 79 no-argument read tools return without error on the new firmware.

## Findings that drive the work

1. Integration API 11.0.99 adds `reportFlowEnabled` to firewall policies (GET, POST, PUT, PATCH). `_PUT_FIELDS` does not include it, so `toggle_zbf_policy` and `update_zbf_policy_v1` PUT a body without it. Every user-defined policy on the console has it set to true, so an update could silently change it.
2. Network 11 aggregated dashboard: AP usage moved from `most_active_aps.usage_by_ap` to `most_active_apps_aps_clients.usage_by` (rows typed `ap`, `client`, `app`); `wifi_connectivity` is empty; a new `radio_activity` section reports channel utilization per band. The endpoint honors `start` and `end` (epoch ms).
3. The legacy `stat/report/{interval}.site` endpoint returns `rc: ok` with zero rows for every interval on Network 11.0.99, while dashboard history has data.
4. Device details add `interfaces.radios[].txPowerMode`, and the radio enums add 802.11ah at 0.9 GHz.
5. Official operations with no tool: `GET /v1/sites`, the WiFi broadcast reads, `GET /v1/sites/{siteId}/networks/{networkId}`, the ACL rule reads, plus writes deferred below.
6. `scripts/spec_coverage.py` matches by path only and does not expand templated paths such as the Protect accessory `/{kind}` routes.

## Wave 1: compatibility fixes (TDD)

- ZBF official: add `reportFlowEnabled` to `_PUT_FIELDS`, the formatted policy (`report_flow_enabled`), and a `report_flow` argument on `create_zbf_policy_v1` and `update_zbf_policy_v1` (sent only when passed).
- Dashboard: read AP usage from the Network 11 section with fallback to the 10.x section; add a `radio_activity` summary; add an optional `hours` window (sent as `start` and `end`).
- `get_site_traffic_history`: return a `note` when the report is empty that explains the Network 11 behavior and points to `get_dashboard_summary`.
- Device details: return `tx_power_mode`.
- `VERIFIED_VERSIONS`: Network 11.0.99, Protect 7.3.74 after the live sweep passes.

## Wave 2: official read tools (Tier 1)

- `lookups`: `list_sites_v1`, `get_network_v1`.
- New `wifi_official` (group `core`): `list_wifi_broadcasts_v1`, `get_wifi_broadcast_v1`. Allow-listed output only; passphrases and RADIUS secrets are never returned (only counts and network references).
- New `acl_official` (group `security`): `list_acl_rules_v1`, `get_acl_rule_v1`.

## Wave 3: tooling and docs

- Coverage by method plus normalized path with operationId, templated placeholder expansion from module constants, `server.py` scanned for `/v1/info`.
- Vendored Network spec 11.0.99 (Protect stays at 7.3.70, matching the installed 7.3 line; 7.4.96 deltas documented).
- Compatibility and feature matrix (`docs/COMPATIBILITY.md`), README, API, TOOLS, CHANGELOG, plugin and marketplace metadata, version 0.10.0.

## Deferred (documented, not built)

- Writes on official WiFi broadcasts, networks, ACL rules and the device RESTART action: they change live connectivity and cannot be verified without changing the network. Existing legacy tools already cover restart and WLAN/network edits.
- Protect 7.4 additions (external arm profiles with arm/disarm, `subscribe/updates`, speaker `stop-siren`, `antiFlicker` video mode): require Protect 7.4.x, which the console does not run.
- A replacement for the legacy site report on Network 11: no official or verified internal endpoint found.

## Verification

- Unit and contract tests with respx for every change, with `UNIFI_HOST` and `UNIFI_API_KEY` unset (CI parity), coverage at or above 80%.
- Live checks read-only only, through the write-blocking sweep (`GET` plus known read-only report POSTs).
- One code review and one security review on the combined diff.
