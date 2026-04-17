# Auth Discovery Results

*Template: run `uv run pytest tests/integration/test_auth_discovery_sweep.py -m integration -v -s` against a live console and populate sections below.*

*Last run: YYYY-MM-DD against console at &lt;UNIFI_HOST&gt;*

## Summary

| Metric | Value |
|---|---|
| Total endpoints tested | N |
| API key successful | N (X%) |
| API key rejected (401/403) | N (X%) |
| Untested (write operations) | N |

## API Key Supported Endpoints

Endpoints confirmed to work with `X-API-Key` header authentication.

| Tool | Endpoint | Method | HTTP Status |
|---|---|---|---|
| (populated from sweep results) | | | |

## Endpoints Requiring Session Auth

Endpoints that returned 401 or 403 with API key auth. These require a
session cookie obtained via username/password login.

| Tool | Endpoint | Method | Status | Notes |
|---|---|---|---|---|
| (populated from sweep results, if any) | | | | |

## Untested Endpoints

Write and mutation endpoints excluded from the read-only sweep.

| Tool | Endpoint | Reason not tested |
|---|---|---|
| create_firewall_rule | POST /proxy/network/... | Mutates state |
| delete_firewall_rule | DELETE /proxy/network/... | Mutates state |
| restart_device | POST /proxy/network/... | Destructive (Tier 2) |
| upgrade_firmware | POST /proxy/network/... | Destructive (Tier 2) |
| block_client | POST /proxy/network/... | Mutates state (Tier 2) |
| (add others as tool modules are implemented) | | |

## How to Update This File

1. Set environment variables:
   ```
   export UNIFI_HOST=https://192.168.x.x
   export UNIFI_API_KEY=your_api_key_here
   ```

2. Run the sweep:
   ```
   uv run pytest tests/integration/test_auth_discovery_sweep.py -m integration -v -s 2>&1 | tee /tmp/sweep.txt
   ```

3. Copy the `Auth Discovery Summary` and `All tested endpoints` sections
   from the output into the tables above.

4. Update the "Last run" date and console IP at the top of this file.
