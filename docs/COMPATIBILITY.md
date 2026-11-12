# Compatibility and feature matrix

Research date: 2026-11-12. Applies to unifi-mcp 0.10.0.

## Versions

| Product | Tested by this release | Earlier releases tested | Published by Ubiquiti on the research date |
|---|---|---|---|
| UniFi OS (UDM Pro) | 6.0.17 | 5.0.16 | not checked beyond the console |
| UniFi Network application | 11.0.99 | 10.6.106 | Network API 11.0.97 ([index](https://developer.ui.com/llms.txt)) |
| UniFi Protect application | 7.3.74 | 7.2.105 | Protect API 7.4.96 ([spec](https://developer.ui.com/protect/v7.4.96/openapi.json)) |
| Site Manager API | 1.0.0 (mocked tests only) | 1.0.0 | 1.0.0 |

"Tested" means the read-only live sweep below, plus unit and contract tests. No write tool was run against a console for this release.

The console serves its own Network spec (`GET /proxy/network/api-docs/integration.json`). The 11.0.99 copy is vendored as `docs/specs/network-11.0.99.json`; it lists the same operations as the published 11.0.97 spec. The Protect spec stays at 7.3.70, which matches the installed 7.3 line. `get_server_info` reports drift when a console's major.minor differs from the tested versions.

### Prerequisites and upgrade notes

- Network 11.0.99 requires UniFi OS 6.0 or newer ([UniFi OS release listing](https://ubiquiti-networks-forum.de/board/thread/15133-beta-unifi-os-dream-machines-6-x-x/?postID=178847)). Network 11 migrates statistics to PostgreSQL on first start ([report](https://borncity.com/news/unifi-network-11-postgresql-migration-loescht-bisherige-statistikverlaeufe/)); the console records a `postgres_migration` timestamp in the dashboard payload.
- The Protect 7.4 tools listed below need Protect 7.4.x. This project never upgrades firmware; upgrade through the UniFi UI, then run `uv run python scripts/spec_diff.py`.

## What changed upstream

Sources: [Introducing UniFi Network 11](https://blog.ui.com/article/introducing-unifi-network-11) (Ubiquiti, 2026-10-12), the console's spec diff (`scripts/spec_diff.py`, 10.6.106 to 11.0.99, and Protect 7.3.70 to 7.4.96), and read-only probes of the console.

### Network 11 (installed)

| Change | Source | Effect on unifi-mcp |
|---|---|---|
| Firewall policies gain `reportFlowEnabled` (GET, POST, PUT, PATCH) | spec diff | Fixed. GET-merge-PUT tools dropped the field; it is now kept, reported and settable |
| Device radios gain `txPowerMode`; radio enums add 802.11ah at 0.9 GHz | spec diff | `get_device_details_v1` returns `tx_power_mode`; other radio fields pass through |
| Aggregated dashboard: AP usage moved to `most_active_apps_aps_clients.usage_by` (typed rows), `wifi_connectivity` empty, new `radio_activity` | console probe | `get_dashboard_summary` reads both layouts and returns `radio_activity` |
| Dashboard honors `start` and `end` (epoch ms) | console probe (1 h to 30 days) | `get_dashboard_summary(hours=...)` |
| Legacy `stat/report/{interval}.site` answers ok with zero rows for every interval | console probe | `get_site_traffic_history` returns a note pointing to the dashboard |
| Re-engineered telemetry, Time Machine topology, Network Lists with external URLs, WiFi WAN, SD-WAN policies, Matter and Thread visibility, AI threat explanations | Ubiquiti blog | No official API operations were added for these in 11.0.97 or 11.0.99, so no tools |

### Protect 7.4 (published, not installed)

| Operation | Prerequisite | Disposition |
|---|---|---|
| `GET/POST /v1/external/arm-profiles`, `GET/PATCH/DELETE /v1/external/arm-profiles/{id}` | Protect 7.4.x with the external Alarm Manager | Deferred: cannot be verified on 7.3.74 |
| `POST /v1/external/arm-profiles/{id}/actions/arm` and `/disarm` | as above | Deferred, would be Tier 2 |
| `GET /v1/subscribe/updates` (WebSocket) | Protect 7.4.x | Deferred |
| `POST /v1/speakers/{id}/stop-siren` | Protect 7.4.x | Deferred, would extend `run_protect_device_action` |
| Camera `videoMode` value `antiFlicker`; sensor `isMountedIncorrectly`; NVR `featureFlags.useExternalAlarmManager` | Protect 7.4.x | Response fields pass through where tools return raw data; no tool change needed on 7.3 |

## Feature and API matrix (Network Integration API 11.0.99)

Coverage is by HTTP method and normalized path (`scripts/spec_coverage.py`). Classification: **official** means a published Integration API operation; **verified internal** means an undocumented endpoint observed on the console.

| Feature | Method and path | Auth | Before 0.10.0 | 0.10.0 | Classification | Evidence | Priority | Disposition |
|---|---|---|---|---|---|---|---|---|
| Firewall policy flow reporting | `GET/POST/PUT/PATCH /v1/sites/{siteId}/firewall/policies[/{id}]` | X-API-Key | field dropped on PUT | kept, reported, settable | official | spec 11.0.99, live read | high | done |
| Device radio TX power mode | `GET /v1/sites/{siteId}/devices/{deviceId}` | X-API-Key | not returned | `tx_power_mode` | official | live read | low | done |
| Local sites | `GET /v1/sites` | X-API-Key | none (used internally) | `list_sites_v1` | official | live read | medium | done |
| Application info | `GET /v1/info` | X-API-Key | `get_server_info` | unchanged | official | live read | n/a | covered |
| Network detail | `GET /v1/sites/{siteId}/networks/{networkId}` | X-API-Key | none | `get_network_v1` | official | live read | medium | done |
| WiFi broadcasts list and detail | `GET /v1/sites/{siteId}/wifi/broadcasts[/{id}]` | X-API-Key | legacy `wlanconf` only | `list_wifi_broadcasts_v1`, `get_wifi_broadcast_v1` | official | live read, passphrase redaction checked | medium | done |
| ACL rules list and detail | `GET /v1/sites/{siteId}/acl-rules[/{id}]` | X-API-Key | ordering only | `list_acl_rules_v1`, `get_acl_rule_v1` | official | live list (empty), spec contract | medium | done |
| WiFi broadcast writes | `POST`, `PUT`, `DELETE /v1/sites/{siteId}/wifi/broadcasts[/{id}]` | X-API-Key | legacy WLAN tools | none | official | spec | low | deferred: changes live WiFi, not verifiable without changing the network |
| Network writes | `POST`, `PUT`, `DELETE /v1/sites/{siteId}/networks[/{id}]` | X-API-Key | legacy `networkconf` tools | none | official | spec | low | deferred, same reason |
| ACL rule writes | `POST`, `PUT`, `DELETE /v1/sites/{siteId}/acl-rules[/{id}]` | X-API-Key | v2 MAC filter tools | none | official | spec | low | deferred, same reason |
| Device restart | `POST /v1/sites/{siteId}/devices/{deviceId}/actions` (`RESTART`) | X-API-Key | legacy `restart_device` | unchanged | official | spec | low | deferred, existing tool covers it |
| Adopt and remove devices | `POST /v1/sites/{siteId}/devices`, `DELETE .../devices/{deviceId}` | X-API-Key | legacy `adopt_device`, `forget_device` | unchanged | official | spec | low | deferred |
| Create vouchers | `POST /v1/sites/{siteId}/hotspot/vouchers` | X-API-Key | legacy create | unchanged | official | spec | low | deferred |
| Dashboard (Network 11 layout and window) | `GET /proxy/network/v2/api/site/{site}/aggregated-dashboard?start=&end=` | X-API-Key | 10.x layout only | both layouts, `hours` | verified internal | live read | high | done |
| Site report history | `POST /proxy/network/api/s/{site}/stat/report/{interval}.site` | X-API-Key | returned rows on 10.x | explains empty result | verified internal (empty on 11) | live read | medium | done; no replacement endpoint found |
| Every other read tool | various | X-API-Key | | | | 77 of 79 no-argument read tools returned without error on 11.0.99 | | re-verified |

Coverage summary (method and path): Network 82.2% (60 of 73), Protect 91.9% (68 of 74, spec 7.3.70), Site Manager 64.3% (9 of 14).

Remaining Network gaps are the 13 write operations in the deferred rows. Remaining Protect gaps on 7.3.70: talkback session, file upload and listing, POS transactions, and single user lookups. Site Manager gaps: the connector proxy (`/v1/connector/consoles/{id}/*`).

## Internal (undocumented) endpoints still in use

These have no public contract and can change with any Network release. The tools fail soft with an error naming the endpoint.

- v2: `aggregated-dashboard`, `speedtest`, `wan/load-balancing/status`, `traffic-flows`, `system-log/all` and `/count`, `firewall-policies`, `acl-rules`, `content-filtering`, `vpn/connections`, `wireguard/users`
- legacy: `stat/device`, `stat/sta`, `stat/sysinfo`, `stat/health`, `stat/report`, `stat/rogueap`, `stat/stadpi`, `cmd/devmgr`, `cmd/backup`, `rest/networkconf`, `rest/wlanconf`, `rest/setting`, `rest/dynamicdns`, `rest/scheduletask` and the other `rest/` collections used by the legacy tools

All of them answered on 11.0.99 during the read-only sweep, except `stat/report`, which answered with no rows.

## Verification for this release

| Kind | What |
|---|---|
| Mocked unit and contract tests | 1597 passing, 97.5% line coverage. New: Network 11 shapes, `reportFlowEnabled` through create, update and toggle (including the preview drift guard), dashboard layouts and window validation, empty report note, `tx_power_mode`, the six new read tools (validation, pagination, errors, no passphrase in output), method-aware coverage scanner, Protect subscription channel allow-list |
| Live, read-only | Write-blocking sweep (GET plus known read-only report POSTs) of every no-argument read tool and of every new or changed tool on Network 11.0.99 and Protect 7.3.74, including a check that no WiFi passphrase appears in any output |
| Not verified live | Every write tool, the `report_flow` argument on create and update, ACL rule detail (no rules on the test console), the Protect 7.4 operations |

## Permissions

All Network and Protect tools use a local-console API key (`X-API-Key`) from Settings, Control Plane, Integrations. The key has the console's full Integration API permissions; there are no narrower scopes. WiFi passphrases are visible to the key through the official API, which is why the WiFi tools allow-list their output.
