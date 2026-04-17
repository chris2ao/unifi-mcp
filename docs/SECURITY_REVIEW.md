# Security Review: chris2ao-unifi-mcp

**Date:** 2026-04-14 (initial), updated 2026-04-17 for Phase 2
**Reviewer:** DevSecOps Engineer (Claude Opus 4.6)
**Scope:** Phase 1 MVP + Phase 2 Protect (86 Network tools + 12 Protect tools)
**Codebase:** 208 tests passing, 15 skipped integration tests

---

## Summary

| Severity | Count (cumulative through 2026-04-17) |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 2 (both fixed in 2026-04-14 review) |
| MEDIUM | 3 (all fixed in 2026-04-14 review) |
| LOW/INFO | 5 (Phase 1) + 4 (Phase 2 addendum) |

**Overall Assessment:** The codebase is well-structured with a solid security foundation. The API key is transmitted via header only, no credentials are hardcoded, test fixtures are clean, and the preview-confirm pattern for destructive operations is consistently applied. Two HIGH issues (secret leakage in preview dicts) and three MEDIUM issues (missing Tier 2 classifications) were found and fixed in this review.

---

## 1. Safety Tier Assignments (safety.py)

### HIGH-001: `update_wlan` preview leaked passphrase (FIXED)

The `update_wlan` function echoed the caller's `updates` dict verbatim in the preview response. If the caller included `x_passphrase` in the updates, it would appear in the preview dict returned to the MCP client.

**Fix:** Added `x_passphrase` stripping to the preview path, matching the pattern already used in `create_wlan`.

**File:** `src/unifi_mcp/tools/network/wifi.py`

### HIGH-002: `update_radius_profile` preview leaked shared secrets (FIXED)

The `update_radius_profile` preview echoed the full `updates` dict. RADIUS auth/acct server entries contain `x_secret` (shared secret) fields. The create path correctly showed only `auth_server_count`, but update did not.

**Fix:** Replaced `auth_servers` and `acct_servers` lists with safe count-only summaries in the preview path.

**File:** `src/unifi_mcp/tools/network/radius.py`

### MEDIUM-001: `toggle_wlan` missing from `_TIER2_TOOLS` (FIXED)

Disabling an SSID disconnects all wireless clients on that network. This is a disruptive mutation that had a confirm flow in the implementation but was not registered in the safety tier dict, meaning the `SafetyManager` could not track or audit it.

**Fix:** Added `"toggle_wlan": "wifi"` to `_TIER2_TOOLS`.

### MEDIUM-002: `adopt_device` and `rf_scan` missing from `_TIER2_TOOLS` (FIXED)

Both functions had confirm patterns in their implementations but were not registered in `_TIER2_TOOLS`. `adopt_device` changes the device management state, and `rf_scan` briefly disrupts wireless service.

**Fix:** Added `"adopt_device": "devices"` and `"rf_scan": "devices"` to `_TIER2_TOOLS`.

### MEDIUM-003: `add_mac_filter` and `delete_mac_filter` were Tier 1 (FIXED)

MAC ACL rules can block network access for specific devices. Adding or deleting these rules is functionally equivalent to `block_client`/`unblock_client`, which are correctly classified as Tier 2.

**Fix:** Added both to `_TIER2_TOOLS` and added the `confirm` parameter with preview-confirm flow to both functions. Updated tests to verify the new pattern.

**Files:** `src/unifi_mcp/safety.py`, `src/unifi_mcp/tools/network/mac_acl.py`, `tests/unit/test_network_remaining.py`

### INFO-001: Tier classifications verified correct for all other tools

Cross-referenced all 86 tool functions across 19 modules against the `_TIER2_TOOLS` dict:

- All create/update/delete operations for networks, firewall rules, firewall groups, ZBF policies, WLANs, VPNs, port forwards, RADIUS profiles, port profiles, and backups are correctly classified as Tier 2.
- All read-only operations (list, get, stats, topology, traffic flows, DPI, health, alarms, events) are correctly Tier 1.
- `locate_device`, `rename_device`, `set_client_alias`, `reconnect_client`, `create_backup`, `create_voucher`, `create_webhook`, `delete_webhook` are Tier 1, which is appropriate for non-destructive or low-impact operations.
- Cache categories match tool module groupings consistently.

### INFO-002: `reconnect_client` is Tier 1

`reconnect_client` kicks and forces a rejoin. This is mildly disruptive but non-destructive (the client reconnects automatically). Tier 1 classification is acceptable, though a case could be made for Tier 2 if the operator prefers maximum caution.

---

## 2. Auth Handling (auth/client.py)

### INFO-003: Auth implementation is clean

- API key is sent exclusively via the `X-API-Key` header (line 17). It is never appended to URLs, query strings, or request bodies.
- The `DiscoveryRegistry` logs only endpoint, method, status code, and timestamp. No credentials appear in discovery entries.
- Error messages reference `self.config.unifi_host` (the hostname) but never `self.config.unifi_api_key`. The API key value cannot leak through error messages.
- SSL verification defaults to `False` in `UnifiConfig` (line 10 of config.py), which is correct for self-signed certificates common on UniFi consoles.
- httpx timeout is set to 30 seconds (line 19 of client.py), which is reasonable for a local network appliance.

---

## 3. Secret Scanning

### INFO-004: No hardcoded secrets found

Scanned all `.py` files in `src/` and `tests/` for patterns matching `api_key`, `password`, `secret`, `token`, `passphrase`, and `credential`.

**Source code (`src/`):** All references are structural (config field names, header key names, parameter names). No hardcoded credential values.

**Tests (`tests/`):** All API key values use `monkeypatch.setenv` with obviously-fake test values (`"test-key"`, `"test-api-key"`, `"test-key-123"`). The RADIUS test uses `"secret"` as a placeholder `x_secret` value, which is appropriate for a mock test.

**Test fixtures (`tests/fixtures/`):** All 12 JSON fixture files contain only structural data (device info, network configs, etc.). No credentials, API keys, or secrets.

**.gitignore:** Includes `.env` pattern, preventing accidental commits of environment files with real credentials. Also excludes `.venv/` and `venv/`.

---

## 4. Tool Safety Patterns

### Spot-check results (4 Tier 2 tools verified)

**`create_firewall_rule` (firewall.py):**
- `confirm=False`: Returns preview dict with params, no API call. Verified.
- `confirm=True`: Makes POST, calls `invalidate_cache("firewall")`. Verified.
- No bypass path.

**`restore_backup` (backups.py):**
- `confirm=False`: Returns preview with filename and warning. No API call. Verified.
- `confirm=True`: Makes POST, calls `invalidate_cache("backups")`. Verified.
- No bypass path.

**`block_client` (clients.py):**
- `confirm=False`: Returns preview with MAC. No API call. Verified.
- `confirm=True`: Makes POST to stamgr, calls `invalidate_cache("clients")`. Verified.
- No bypass path.

**`create_wlan` (wifi.py):**
- `confirm=False`: Returns preview with passphrase stripped (`x_passphrase` excluded). Verified.
- `confirm=True`: Makes POST with full payload including passphrase. Verified.
- No bypass path.

All Tier 2 tools follow the same pattern: the `confirm` parameter is a required boolean with `False` default. The `if not confirm:` guard is the first branch, ensuring no API call can be made without explicitly passing `confirm=True`.

---

## 5. Input Validation

### INFO-005: Input validation relies on API-side enforcement

Tool functions do not perform client-side validation of inputs (e.g., MAC address format, IP address format, VLAN range). This is acceptable for a Phase 1 MVP because:

1. The UniFi API validates all inputs and returns structured error responses (400 status).
2. The `UnifiError` class with `ErrorCategory.VALIDATION_ERROR` properly surfaces these errors.
3. httpx handles URL encoding and JSON serialization safely, preventing injection.
4. There is no SQL layer or template rendering, so injection risks are minimal.

**Recommendation for Phase 2:** Consider adding lightweight client-side validation for MAC addresses (regex), IP addresses, and VLAN ranges (1-4094) to provide faster feedback and better error messages.

---

## Changes Made in This Review

| File | Change |
|------|--------|
| `src/unifi_mcp/tools/network/wifi.py` | Strip `x_passphrase` from `update_wlan` preview |
| `src/unifi_mcp/tools/network/radius.py` | Strip server secrets from `update_radius_profile` preview |
| `src/unifi_mcp/safety.py` | Add `toggle_wlan`, `adopt_device`, `rf_scan`, `add_mac_filter`, `delete_mac_filter` to `_TIER2_TOOLS` |
| `src/unifi_mcp/tools/network/mac_acl.py` | Add confirm pattern to `add_mac_filter` and `delete_mac_filter` |
| `tests/unit/test_network_remaining.py` | Update MAC ACL tests for new confirm pattern |

**Test results after changes:** 183 passed, 0 failed.

---

## Phase 2 Addendum (2026-04-17)

Phase 2 Protect tools were integrated in commit `4e34434`. The codebase grew from 183 to 208 tests. This section documents the security implications of the new mutations, stubs, and infrastructure changes.

### New mutation: `update_camera_name` (Tier 1)

The `update_camera_name` function performs a cosmetic camera rename via `PATCH /proxy/protect/integration/v1/cameras/{id}`. The operation accepts a `name` parameter and applies it directly to the camera's label in the UniFi Protect console.

**Tier 1 classification rationale:** The operation is cosmetic and identical in risk profile to existing Tier 1 mutations like `rename_device` (network) and `set_client_alias` (clients). No access control change, no security impact. Not added to `_TIER2_TOOLS` in `safety.py`. No preview-confirm flow required.

**Cache invalidation:** Invalidates `protect_cameras` cache on success.

**Testing:** Live-verified against the G5 PTZ (2026-04-17 session).

**Risk assessment: LOW.** Camera names are visible labels only; they do not affect recording, access control, or network behavior.

### PRODUCT_UNAVAILABLE stubs (5 new tools)

Five tools return a structured error envelope without making network calls:

- `set_camera_recording_mode` (cameras.py)
- `ptz_camera` (cameras.py)
- `reboot_camera` (devices.py)
- `list_motion_events` (events.py, already present from initial Phase 2 read-only commit)
- `list_smart_detections` (events.py, already present from initial Phase 2 read-only commit)

Each stub raises `NotImplementedError` with a message indicating the endpoint is not yet exposed by UniFi. The implementation never reaches the network, even when called with `confirm=True`. Unit tests assert no API call is made (`respx.mock(assert_all_called=False)` with `not route.called`).

**Security implication: NONE.** No authentication, no mutation, no data exposure. Worth noting that when UniFi later exposes these endpoints, the stubs must be re-reviewed. The following classifications will be required:

- `reboot_camera`: Tier 3 (mutates camera state)
- `set_camera_recording_mode`: Tier 3 (mutates camera state)
- `ptz_camera`: Tier 3 (mutates camera state)
- `list_motion_events`: Tier 1 (read-only)
- `list_smart_detections`: Tier 1 (read-only)

### New client method: `UnifiClient.patch(path, json)`

Added in session 2026-04-17 to support PATCH-based mutations (Protect's camera update surface uses PATCH). The method follows the same pattern as PUT and POST.

**Implementation:** Uses the same `_request()` helper as the other HTTP methods, so the same error categorization, discovery logging, and non-JSON rejection apply.

**Security implication: NONE new.** PATCH uses the same X-API-Key header, the same httpx client, and the same error handling. No new attack surface.

### Site-UUID resolver (in `auth/client.py`)

Added a lazy site UUID resolver that fetches `/proxy/network/integration/v1/sites` on the first path containing a `{site_id}` placeholder, then caches the UUID for the lifetime of the client.

**Error handling:** If a misconfigured console returns an unexpected site list, the resolver raises `NOT_FOUND` rather than silently using the wrong site. This is the correct fail-safe behavior.

**Security implication: LOW.** The sites endpoint returns internal UUIDs (not credentials). The lookup uses the same authenticated channel. No new auth boundaries crossed.

### Endpoint repointing (6 tools)

Six tools in Phase 1 were repointed to current endpoints or stubbed as `PRODUCT_UNAVAILABLE`:

- `get_events`: Repointed to Protect events
- `list_webhooks`: Repointed to current webhook endpoint
- `4x traffic_flows tools`: Repointed or stubbed

No new secrets handled. No new auth boundaries crossed.

### Phase 2 sign-off

No new HIGH or MEDIUM findings. The Phase 2 tool surface is smaller and simpler than Phase 1 (12 tools vs 86). The single new mutation (`update_camera_name`) is cosmetic and matches existing Tier 1 rename patterns. The five PRODUCT_UNAVAILABLE stubs have no security surface. Tests grew from 183 to 208 passed. Coverage unchanged on infrastructure modules.
