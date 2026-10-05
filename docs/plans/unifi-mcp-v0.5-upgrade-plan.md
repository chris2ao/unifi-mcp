# unifi-mcp v0.5+ Upgrade Evaluation and Plan

**Date:** 2026-10-04
**Baseline:** unifi-mcp v0.4.1 (103 tools with Network + Protect loaded)
**Console under test:** UDM Pro, UniFi Network **10.6.106** (was 10.2.105 when the tools were built), UniFi Protect **7.2.105** (was 7.0.104)

## 1. How this was evaluated

Evidence, in order of trust:

1. **Live probes against the console** with the local API key (GET requests, plus read-only POST queries for logs and flows). No mutations were sent.
2. **Official OpenAPI specs.** Two discoveries make this repeatable:
   - The console serves its own Network spec at `GET /proxy/network/api-docs/integration.json` (OpenAPI 3.1, version matches the running firmware, 44 paths, 380 schemas). It accepts the API key.
   - Ubiquiti publishes every product spec at `https://developer.ui.com/{service}/{version}/openapi.json`, with an index at `https://developer.ui.com/llms.txt`. Current: Network v10.6.106, Protect v7.3.70, Site Manager v1.0.0.
3. Web research and a survey of other UniFi MCP servers (sirkirby/unifi-mcp, enuno/unifi-mcp-server, claytono/go-unifi-mcp). Used for ideas only; several of their claims did not survive live verification.

## 2. Regressions on Network 10.6.106 (fix first)

| Tool | Endpoint today | Live result | Fix |
|---|---|---|---|
| `get_events` | `POST /v2/api/site/{site}/system-log/{triggers,threats}` | **404** | Use `POST /v2/api/site/{site}/system-log/all` with body `{timestampFrom, timestampTo, pageNumber, pageSize}`. Supports `categories` (e.g. `SECURITY`, `CLIENT_DEVICES`, `AUDIT`, `VPN`, `SOFTWARE_UPDATES`) and `severities` (e.g. `HIGH`, `VERY_HIGH`) filters. Verified: 4,767 events / 7 days, 749 `THREAT_BLOCKED` under `SECURITY`. |
| `get_alarms` | `GET /api/s/{site}/stat/alarm` | **404** | Re-implement on `system-log/all` filtered to high severities, or retire. |
| `list_webhooks`, `create_webhook`, `delete_webhook` | `/v2/api/site/{site}/notifications` | **404** | No replacement found among 10 candidate paths. Convert to `PRODUCT_UNAVAILABLE` stubs now; discover the new path later by capturing the UI's network calls (Alarm Manager page) with the browser tool. |
| Legacy firewall (8 tools) | `/rest/firewallrule`, `/rest/firewallgroup` | 200, **empty** | Console is fully on Zone-Based Firewall. Keep for pre-ZBF consoles, but document that they are inert after migration. Firewall groups are superseded by Traffic Matching Lists (section 4). |

New helper: `get_event_counts` on `POST /v2/api/site/{site}/system-log/count` (returns counts per category, event key, and type for a time window).

## 3. Stubs that can now become real tools

| Stub(s) | Status on current firmware | Implementation |
|---|---|---|
| `list_traffic_flows`, `get_top_talkers`, `filter_flows_by_app`, `filter_flows_by_client` (4) | **Unlocked.** `POST /v2/api/site/{site}/traffic-flows` returns 200 with the API key (`GET` is 405, which is why the old probe concluded it was missing). | Body: `{timestampFrom, timestampTo, pageNumber, pageSize}`. Verified filters: `search_text` (176 hits for "google"), `direction` (`["outgoing"]`), `protocol` (`["UDP"]`), `action` (`["blocked"]`), `risk` (`["low"]`). Each flow has source/destination (ip, port, mac, device name, zone, region, domains), service, policies matched, risk, and `traffic_data` bytes/packets. Top talkers are computed client-side by aggregating `traffic_data.bytes_total`. Result sets are large (10,000+ per hour), so always cap `pageSize` and time window. |
| `ptz_camera` | **Unlocked** (Protect spec 7.3.70, endpoints answer on 7.2.105) | `POST /v1/cameras/{id}/ptz/goto/{slot}`, `POST /v1/cameras/{id}/ptz/patrol/start/{slot}`, `POST /v1/cameras/{id}/ptz/patrol/stop`. |
| `list_motion_events`, `list_smart_detections` | **Partially unlocked.** No REST history; events are only on the WebSocket `GET /v1/subscribe/events`. | Replace with a bounded `watch_protect_events(seconds, types)` tool (collect for N seconds, max ~120, then return), and optionally a background ring buffer started by `load_protect_tools`. Requires a WebSocket dependency (`websockets` or `httpx-ws`). |
| `set_camera_recording_mode` | **Still unavailable.** Camera PATCH schema in 7.3.70 has no recording fields. | Keep stub; refresh message to cite Protect 7.2.105 / spec 7.3.70. |
| `reboot_camera` | **Still unavailable.** No reboot path in the 7.3.70 spec. | Keep stub; refresh message. |

## 4. New capabilities: Network Integration API (official contract)

All paths below are under `/proxy/network/integration/v1`. Every list endpoint was verified 200 on 10.6.106 with the API key.

| Area | Endpoints | Proposed tools | Tier | Value |
|---|---|---|---|---|
| **DNS Policies** (local DNS records: `A_RECORD`, `AAAA_RECORD`, `CNAME_RECORD`, `MX_RECORD`, `TXT_RECORD`, `SRV_RECORD`, `FORWARD_DOMAIN`) | `GET/POST /sites/{id}/dns/policies`, `GET/PUT/DELETE .../{dnsPolicyId}` | `list_dns_policies`, `get_dns_policy`, `create_dns_policy`, `update_dns_policy`, `delete_dns_policy` | T1 read, T2 write | **High.** Gateway-side local DNS and conditional forwarding, complements Pi-hole. |
| **Traffic Matching Lists** (`PORTS`, `IPV4_ADDRESSES`, `IPV6_ADDRESSES`) | `GET/POST /sites/{id}/traffic-matching-lists`, `GET/PUT/DELETE .../{listId}` | list/get/create/update/delete (5) | T2 write | **High.** Reusable IP/port objects referenced by ZBF policies (`trafficMatchingListId`). Replaces firewall groups. |
| **Firewall policies (official)** | `GET/PUT/PATCH/DELETE /firewall/policies/{id}`, `GET/PUT /firewall/policies/ordering?sourceFirewallZoneId=&destinationFirewallZoneId=` | `get_zbf_policy`, `toggle_zbf_policy` (PATCH), `get_zbf_policy_order`, `reorder_zbf_policies` | T2 write | **High.** PATCH avoids the full-body PUT pitfalls; ordering was previously impossible. |
| **Custom firewall zones** | `POST /firewall/zones`, `PUT/DELETE /firewall/zones/{id}` | `create_zbf_zone`, `update_zbf_zone`, `delete_zbf_zone` | T2 | Medium |
| **Device statistics** | `GET /devices/{id}/statistics/latest` | `get_device_statistics` (CPU, memory, load averages, uplink, per-interface stats) | T1 | Medium |
| **PoE power cycle** | `POST /devices/{id}/interfaces/ports/{portIdx}/actions` `{"action":"POWER_CYCLE"}` | `power_cycle_port` | T2 | **High.** Remotely bounce a hung camera or AP. |
| **Device restart (official)** | `POST /devices/{id}/actions` `{"action":"RESTART"}` | Migrate `restart_device` internals (optional) | T2 | Low |
| **Pending adoption** | `GET /pending-devices` | `list_pending_devices` | T1 | Medium |
| **Guest authorization** | `POST /clients/{id}/actions` `AUTHORIZE_GUEST_ACCESS` / `UNAUTHORIZE_GUEST_ACCESS` | `authorize_guest`, `unauthorize_guest` | T2 | Medium |
| **Network references** | `GET /networks/{id}/references` | `get_network_references`; also call it from `delete_network` preview so the preview lists what would break | T1 | **High** (safety) |
| **Hotspot vouchers** | `GET/POST/DELETE /hotspot/vouchers` (DELETE supports `filter`), `GET/DELETE .../{voucherId}` | `get_voucher`, `delete_voucher`, `delete_vouchers` (by filter) | T2 delete | Low |
| **ACL rule ordering** | `GET/PUT /acl-rules/ordering` | `get_acl_order`, `reorder_acl_rules` | T2 | Low |
| **Supporting resources** | `/wans`, `/vpn/servers`, `/vpn/site-to-site-tunnels`, `/radius/profiles`, `/device-tags`, `/dpi/categories`, `/dpi/applications` (2,112 apps), `/countries` | `list_wans`, `list_site_to_site_tunnels`, `list_device_tags`, `lookup_dpi_application` (search by name, needed to build app-based traffic rules) | T1 | Medium |
| **Switching** | `/switching/switch-stacks`, `/switching/lags`, `/switching/mc-lag-domains` (+ get by id) | `list_switch_stacks`, `list_lags`, `list_mc_lag_domains` | T1 | Low for this console (all empty) |
| **WiFi broadcasts** | full CRUD | None for now. Legacy `wlanconf` tools carry `mac_filter_*` fields that the homenet skills depend on. Revisit only if legacy breaks. | | Low |

**Client plumbing required (do this before the tools above):**

- Integration list endpoints paginate with `offset`/`limit` and default to **25**. Live examples: firewall policies 88 total, clients 31, DPI applications 2,112. Add a `get_all_pages()` helper with a hard cap.
- Pass through the official `filter` query parameter (`name.like('guest*')`, `and(...)`, `not(...)`), so tools can filter server-side.

## 5. New capabilities: internal v2 and legacy endpoints (live-verified, no public contract)

These work with the API key today but can change without notice. Each tool should fail soft with a clear message.

| Endpoint | Proposed tool | Value |
|---|---|---|
| `GET /v2/api/site/{site}/aggregated-dashboard` (WiFi Doctor, ISP metrics, CyberSecure, most active clients/APs/apps, WAN activity, upgradable device count) | `get_dashboard_summary` | **High.** One call for "how is my network doing". |
| `GET /v2/api/site/{site}/speedtest` (166 results on file) | `get_speedtest_history` | **High** |
| `GET /v2/api/site/{site}/wan/load-balancing/status` (console has 2 WANs) | `get_wan_status` | **High** |
| `GET /v2/api/site/{site}/content-filtering` | `list_content_filters` (+ later update) | Medium |
| `GET /v2/api/site/{site}/nat` | `list_nat_rules` | Medium |
| `GET /v2/api/site/{site}/routes`, `GET /api/s/{site}/rest/routing` | `get_routing_table`, `list_static_routes` | Medium |
| `GET /v2/api/site/{site}/trafficroutes` | `list_traffic_routes` (policy-based routing) | Medium |
| `GET /v2/api/site/{site}/vpn/connections`, `/wireguard/users` | `list_vpn_connections` | Medium |
| `GET /v2/api/site/{site}/clients/history` | Upgrade `list_all_clients` (adds last network, last IP, last uplink) | Medium |
| `GET /api/s/{site}/stat/rogueap` (187 neighbor APs) | `list_neighbor_aps` | Medium (channel planning) |
| `GET /api/s/{site}/stat/report/{5minutes,hourly}.site` | `get_site_traffic_history` | Medium |
| `GET /api/s/{site}/rest/scheduletask`, `/rest/dynamicdns`, `/rest/setting` | `list_scheduled_tasks`, `list_dynamic_dns`, `get_site_settings(section)` | Low to medium. **Redact secrets**, since settings include keys and passwords. |
| `GET /api/s/{site}/rest/account` | Skip. Response includes `x_password` for RADIUS users. | Not recommended |

## 6. New capabilities: Protect Integration API (official spec 7.3.70)

Every list endpoint in the 7.3.70 spec answered 200 on the 7.2.105 console. This console has 3 cameras, 1 bridge, 2 users, and no lights, sensors, chimes, sirens, relays, speakers, or alarm hubs.

| Area | Endpoints | Proposed tools | Tier |
|---|---|---|---|
| **PTZ** | `ptz/goto/{slot}`, `ptz/patrol/start/{slot}`, `ptz/patrol/stop` | `ptz_goto_preset`, `ptz_start_patrol`, `ptz_stop_patrol` (replaces `ptz_camera` stub) | T1 |
| **Camera settings** | `PATCH /v1/cameras/{id}`: `osdSettings`, `ledSettings`, `lcdMessage`, `micVolume`, `videoMode`, `hdrType`, `smartDetectSettings` | `update_camera_settings` (allow-listed fields only, since PATCH rejects unknown keys with `AJV_PARSE_ERROR`) | T2 for `smartDetectSettings`/`micVolume`, T1 for cosmetic |
| **Mic kill switch** | `POST /v1/cameras/{id}/disable-mic-permanently` | `disable_camera_mic_permanently` | T2, irreversible, extra warning |
| **RTSPS streams** | `POST/GET/DELETE /v1/cameras/{id}/rtsps-stream` | `get_rtsps_streams`, `create_rtsps_stream`, `delete_rtsps_stream` | T2 create/delete. URLs carry access tokens, so never log them. |
| **Alarm Manager / arm modes** | `GET/POST /v1/arm-profiles`, `PATCH/DELETE /v1/arm-profiles/{id}`, `PATCH /v1/arm-profiles/settings`, `POST /v1/arm-profiles/enable`, `POST /v1/arm-profiles/disable`; NVR exposes `armMode` status | `list_arm_profiles`, `get_arm_status`, `arm_alarm`, `disarm_alarm`, `set_active_arm_profile`, `create/update/delete_arm_profile` | T2 for arm/disarm and writes |
| **Alarm webhook trigger** | `POST /v1/alarm-manager/webhook/{id}` | `trigger_alarm_webhook` | T2 |
| **Live views and viewers** | `GET/PATCH /v1/liveviews/{id}`, `POST /v1/liveviews`, `GET/PATCH /v1/viewers/{id}` | `get_liveview`, `create_liveview`, `update_liveview`, `list_viewers`, `set_viewer_liveview` | T1 |
| **Accessory devices** (lights, sensors, chimes, sirens, relays, speakers, bridges, link-stations, alarm-hubs, fobs) | `GET /v1/{kind}`, `GET/PATCH /v1/{kind}/{id}`, plus actions: siren play/stop/test-sound, relay output activate, alarm-hub output trigger, speaker test-sound | Generic `list_protect_devices(kind)`, `get_protect_device(kind, id)`, `update_protect_device(kind, id, settings)`, `run_protect_device_action(kind, id, action, ...)`. Four tools instead of about 30. | T2 for update and actions |
| **Users** | `GET /v1/users`, `GET /v1/ulp-users` (+ by id) | `list_protect_users` | T1 |
| **Events** | WebSocket `/v1/subscribe/events`, `/v1/subscribe/devices` | `watch_protect_events` (section 3) | T1 |
| Skipped | talkback session (audio stream), device asset file upload, POS transactions | Not useful through MCP | |

## 7. Optional: Site Manager cloud API

`https://api.ui.com/v1`: `hosts`, `sites`, `devices`, `isp-metrics/{type}` (GET and POST query, 5m/1h granularity), `sd-wan-configs` (+ status), and a **connector proxy** (`/v1/connector/consoles/{id}/*path`) that reaches Network or Protect remotely without a VPN.

- Requires a **cloud** API key from unifi.ui.com, separate from the local key. This project currently rejects cloud keys by design.
- Proposal: a separate `load_cloud_tools` loader, active only when `UNIFI_CLOUD_API_KEY` is set. Main value is ISP metrics history (latency, packet loss, downtime). Medium priority; the connector proxy is a larger architectural change and should be deferred.

## 8. Server design upgrades

1. **Spec-diff tooling (high value).** Vendor the OpenAPI specs under `docs/specs/` and add `scripts/spec_diff.py` that pulls `/proxy/network/api-docs/integration.json` and the developer.ui.com Protect spec, then diffs them against the vendored copies. After any firmware upgrade, one command shows new and removed endpoints, so we stop discovering changes months later.
2. **Firmware drift check.** `get_server_info` reports console Network/Protect versions next to the "last verified" versions recorded in the code, and flags a mismatch.
3. **Tool budget.** This plan takes the server from 103 to roughly 175 tools. Split `load_network_tools` into sub-loaders (`core`, `security` for firewall/DNS/matching lists, `insights` for flows/logs/dashboard) or add a `UNIFI_TOOL_PROFILE` env var. Keep the always-loaded surface at 5 tools.
4. **Name resolution.** Accept names as well as IDs for zones, networks, and cameras (resolve via cached list calls), so callers do not need a lookup round trip.
5. **Contract tests.** Validate fixtures against the vendored spec schemas, so tests fail when Ubiquiti changes a shape.

## 9. Phased delivery (final, 2026-10-04)

The remote already carries tag `v0.5.0` (commit 8561f1c, timestamped client history) with no GitHub Release and no CHANGELOG entry, so the new releases start at v0.5.1 and v0.5.0 is backfilled.

| Release | Scope |
|---|---|
| v0.5.0 (backfill) | CHANGELOG entry and GitHub Release for the existing tag. No code. |
| v0.5.1 | Network 10.6 regression fixes: `get_events` on `system-log/all` (time window, categories, severities), `get_alarms` on high-severity system log, new `get_event_counts`, webhook tools become `PRODUCT_UNAVAILABLE` stubs, `get_server_info` reports the real package version (was hardcoded `0.2.1`), Protect stub messages refreshed for 7.2.105 / spec 7.3.70, Integration API pagination (`offset`/`limit`) and `filter` helper in `UnifiClient`. |
| v0.6.0 | Infrastructure: auto-discovered tool modules, module-level `TIER2_TOOLS` declarations, tool groups for selective loading, firmware drift report, vendored OpenAPI specs + `scripts/spec_diff.py`, generated `docs/TOOLS.md`. Network official API: traffic flows (4 real tools), DNS policies (5), traffic matching lists (5), ZBF policy get/toggle/ordering + custom zones, device statistics, pending devices, PoE power cycle, network references (wired into `delete_network` preview), dashboard summary, speedtest history, WAN status. |
| v0.7.0 | Protect: PTZ (3), camera settings, permanent mic disable, RTSPS streams (3), Alarm Manager arm profiles and arm/disarm, alarm webhook trigger, live view and viewer management, generic accessory device tools (lights, sensors, chimes, sirens, relays, speakers, bridges, link stations, alarm hubs, fobs), Protect users, `watch_protect_events` over WebSocket. |
| v0.8.0 | Network insights and remainder: routing table, static routes, traffic routes, NAT rules, content filters, neighbor APs, site traffic history, VPN connections, scheduled tasks, dynamic DNS, site settings (redacted), guest authorize/unauthorize, v2 client history, voucher get/delete, WANs, site-to-site tunnels, device tags, DPI lookup, switching, ACL ordering. Optional Site Manager cloud loader (`load_cloud_tools`, gated on `UNIFI_CLOUD_API_KEY`). |

### Execution model

1. **v0.5.1 first, alone.** One implementer, then code and security review in parallel, then a release engineer commits and tags. Later work edits some of the same files, so this must land first.
2. **All feature implementation in parallel (12 agents).** File ownership is strict: implementers only create or edit the tool modules and tests they own. They never touch `safety.py`, `_registry.py`, `server.py`, `pyproject.toml`, `uv.lock`, or docs. New tools declare `TOOLS` and `TIER2_TOOLS` at module level; the v0.6.0 infra agent makes both auto-discovered.
3. **Sequential finalization per release (v0.6.0, then v0.7.0, then v0.8.0).** Reviews for all three releases run in parallel; release engineers run strictly in version order. Each release engineer applies CRITICAL/HIGH findings, regenerates `docs/TOOLS.md`, writes the CHANGELOG section, bumps versions, commits only its phase's paths, tags, and runs the full test suite in a clean `git worktree` at the new tag. No tag if tests fail; later tags are only created when the previous tag exists.
4. **Publishing (main session).** Independent verification (tests at every tag, read-only live smoke against the console), push branch and tags, PR to `main`, CI green, merge with a merge commit (squash or rebase would orphan the tag SHAs), GitHub Releases for v0.5.0 (backfill) through v0.8.0, repository description update.

### Agent rules

- Live console: GET requests and the read-only POST queries (`system-log/all`, `system-log/count`, `traffic-flows`) only. Never PUT, PATCH, DELETE, or action POSTs.
- Fixtures are sanitized before commit (documentation IPs, fake MACs, fake IDs, no hostnames from the home network) because the repository is public.
- Every write and every disruptive action is Tier 2 (preview, then `confirm=True`). PoE power cycle, arm/disarm, siren, relay, mic disable, and reorder previews carry explicit impact warnings.
- Tool output never includes the API key, RTSPS stream tokens, or secrets from site settings.

## 10. Still blocked after this plan

- Protect recording mode and camera reboot (no Integration API path in 7.3.70).
- Protect event history over REST (WebSocket only, forward-looking).
- Network webhooks (path moved; needs UI network capture to rediscover).
- Network settings that exist only in the UI with no probed endpoint: IPS/IDS settings, honeypot, ad blocking, Site Magic, teleport (all returned 404 on the paths tried).

## Appendix: probe evidence (2026-10-04)

- Network Integration API: 24/24 list endpoints 200 (`/info`, `/sites`, devices, clients, networks, wifi broadcasts, vouchers, zones, policies, ACL rules + ordering, DNS policies, traffic matching lists, WANs, VPN servers, S2S tunnels, switch stacks, LAGs, MC-LAG, RADIUS, device tags, pending devices, DPI categories/apps, countries). `firewall/policies/ordering` requires `sourceFirewallZoneId` and `destinationFirewallZoneId` query params.
- v2 200: `firewall-policies`, `firewall/zone`, `trafficrules`, `acl-rules`, `qos-rules`, `content-filtering`, `static-dns`, `nat`, `clients/active`, `clients/history`, `apgroups`, `wan/load-balancing/status`, `routes`, `vpn/connections`, `aggregated-dashboard`, `device-tags`, `wireguard/users`, `firewall-app-blocks`, `trafficroutes`, `speedtest`; POST 200: `system-log/all`, `system-log/count`, `traffic-flows`.
- v2 404: `notifications`, `system-log/{triggers,threats}`, `alarms`, `ips/settings`, `honeypot`, `ad-blocking`, `teleport/clients`, `site-magic`, `dns-records`, `static-routes`, `wan/slas`, `port-anomalies`.
- Legacy 200: `stat/device`, `stat/sta`, `rest/user`, `rest/networkconf`, `rest/wlanconf`, `rest/portforward`, `rest/radiusprofile`, `rest/portconf`, `stat/voucher`, `stat/health`, `stat/dpi`, `stat/rogueap`, `stat/report/*.site`, `rest/routing`, `rest/dynamicdns`, `rest/setting`, `rest/scheduletask`, `rest/usergroup`, `rest/wlangroup`, `rest/dhcpoption`, `stat/current-channel`, `cmd/backup list-backups`. Legacy 404: `stat/alarm`, `stat/event`, `stat/ips/event`, `stat/spectrumscan`.
- Protect Integration API 200: `meta/info`, cameras, nvrs, liveviews, viewers, lights, sensors, chimes, sirens, fobs, relays, speakers, bridges, link-stations, alarm-hubs, users, ulp-users, arm-profiles, files/animations. 404: `events`, `recordings`.
