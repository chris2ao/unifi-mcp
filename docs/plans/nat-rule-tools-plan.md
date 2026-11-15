# NAT Rule Tools Implementation Plan

> Execute with the `writing-plans` skill's `executing.md`. Steps use checkboxes; tick them as they finish. After a context reset, re-read this file and resume at the first unchecked box.

**Goal:** Add typed, validated, preview-confirm tools to create, update, toggle and delete gateway NAT rules (DNAT, SNAT, masquerade), release them as v0.11.0, and use them to build the LAN NTP redirect to resolver-a.

**Design:** No separate design document. The owner's request (2026-11-14: "create a tool to do NAT and update the unifi mcp", for the NTP redirect) is the design; the decisions below are pinned here.

**Jira:** CLAUD-929

**Execution:** inline

**Architecture:** A pure module `nat_body.py` validates tool arguments and builds the v2 NAT rule body (like `zbf_policy_filters.py`). A tool module `nat_rules.py` (group `security`) does the HTTP work against `/proxy/network/v2/api/site/{site}/nat`: preview-confirm, CONFLICT when a rule changed after its preview, GET-merge-PUT for updates, and a read-back after every write that reports whether the saved rule matches the intent. `list_nat_rules` stays in `routing.py` (group `insights`); its formatter gains the fields the write tools need.

**Tech stack:** Python 3.12, uv, httpx, pytest + pytest-asyncio + respx, FastMCP.

## Global Constraints

- Endpoint: `GET/POST /proxy/network/v2/api/site/{site}/nat`, `PUT/DELETE /proxy/network/v2/api/site/{site}/nat/{id}`. There is no GET by id: fetch the list and filter on `_id`.
- Body keys (sources: ubiquiti-community/unifi-api `cmd/fields/custom/Nat.json`, terraform-provider-unifi `unifi/nat_resource.go`): `description`, `enabled`, `type` (`DNAT|SNAT|MASQUERADE`), `protocol` (`all|tcp|udp|tcp_udp`), `ip_version` (`IPV4|IPV6`), `in_interface`, `out_interface`, `ip_address`, `port`, `exclude`, `logging`, `rule_index`, `source_filter`, `destination_filter`. Read-only: `_id`, `is_predefined`. Filter keys: `filter_type` (`NONE|ADDRESS_AND_PORT|FIREWALL_GROUPS|NETWORK_CONF`), `address`, `port`, `invert_address`, `invert_port`, `network_conf_id`, `firewall_group_ids`.
- Interface and network ids are legacy `networkconf` `_id` values, the `id` field of `list_networks` (GET `/proxy/network/api/s/{site}/rest/networkconf`). Firewall group ids come from GET `/proxy/network/api/s/{site}/rest/firewallgroup`.
- Every write tool takes `confirm: bool = False`, is listed in the module's `TIER2_TOOLS` with cache category `"routing"`, and calls `client.invalidate_cache("routing")` after a confirmed write (that is the category `list_nat_rules` caches under).
- An HTTP 200 with an empty body is not success: return `executed: False` (reuse `_executed` from `zbf_official.py`).
- After every confirmed write, fetch the list again and compare the saved rule to the intended body; return `verified: True`, or `verified: False` with a `mismatches` dict of `{key: {"intended": x, "saved": y}}`.
- Predefined rules (`is_predefined: true`) are never updated, toggled or deleted: return `VALIDATION_ERROR`.
- Untrusted display text from the controller goes through `validation.clean_text`.
- Additive release: no tool renamed or moved, no parameter removed. Network tools go from 166 to 171.
- Commit subjects: `<type>: CLAUD-929 <description>`. No em dashes anywhere.
- Gates: `uv run pytest -q` (coverage `fail_under = 80`), `uv run python scripts/gen_tool_docs.py --check`.

## Edge Cases

1. `nat_type` changes on update (DNAT to MASQUERADE): the old rule's type-specific fields (`in_interface`, `out_interface`, `ip_address`, `port`) must not carry over, or the merged body fails validation for reasons the caller cannot see. Pinned in Task 4.
2. A filter or translated port with `protocol="all"`: iptables cannot match a port without a protocol, so reject it before the controller does. Pinned in Task 1.
3. A CIDR with host bits set (`192.0.2.5/24`) is almost always a typo: reject with the corrected network in the message. Pinned in Task 1.
4. `rule_index` omitted on create: assign `max(existing) + 1` (0 when there are none) at confirm time, and reject a caller-supplied index that is already taken. Pinned in Task 3.
5. The controller saves a rule but changes or drops a field (an unknown key, a normalized value): the read-back reports `verified: False` with the mismatch instead of claiming success. Pinned in Task 3.

## File Map

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/unifi_mcp/tools/network/nat_body.py` | Create | Pure validation and body building for NAT rules and their filters; no HTTP |
| `src/unifi_mcp/tools/network/nat_rules.py` | Create | `get_nat_rule`, `create_nat_rule`, `update_nat_rule`, `toggle_nat_rule`, `delete_nat_rule` |
| `src/unifi_mcp/tools/network/routing.py` | Modify `_format_nat_rule` (lines 174-188) | Add `exclude`, `logging`, `rule_index`, `is_predefined` to NAT rule output |
| `tests/unit/test_network_nat_body.py` | Create | Unit tests for `nat_body` |
| `tests/unit/test_network_nat_rules.py` | Create | respx tests for the five tools |
| `tests/unit/test_network_routing.py` | Modify | Assert the new formatter fields |
| `tests/fixtures/nat_rules.json` | Create | Three rules: user DNAT, user MASQUERADE, one predefined |
| `tests/fixtures/nat_rules_live.json` | Create (Wave 3) | Sanitized rule as the live controller saved it |
| `docs/API.md`, `docs/TOOLS.md`, `docs/COMPATIBILITY.md`, `README.md` | Modify | Tool reference, regenerated list, coverage note, category table |
| `CHANGELOG.md`, `pyproject.toml`, `.claude-plugin/plugin.json`, `uv.lock` | Modify | v0.11.0 release notes, version, tool counts |

---

## Wave 1: NAT bodies can be built and validated offline

**Done when:** `uv run pytest tests/unit/test_network_nat_body.py tests/unit/test_network_routing.py -q` passes and `build_rule` produces the four NTP redirect bodies listed in Task 1.

### Task 1: `nat_body.py` validation and body building

**Files:**
- Create: `src/unifi_mcp/tools/network/nat_body.py`
- Test: `tests/unit/test_network_nat_body.py`

**Interfaces:**
- Produces:
  - `NAT_TYPES = ("DNAT", "SNAT", "MASQUERADE")`, `PROTOCOLS = ("all", "tcp", "udp", "tcp_udp")`, `IP_VERSIONS = ("IPV4", "IPV6")`
  - `is_error(value) -> bool` (a dict with `error: True`)
  - `build_filter(side: str, spec: dict | None, ip_version: str) -> dict` returns the API filter or a validation error. `spec` keys: `address`, `port`, `invert_address`, `invert_port`, `network_id`, `firewall_group_ids`; anything else is an error. `None` or `{}` gives `{"filter_type": "NONE"}`. `network_id` gives `NETWORK_CONF` with `network_conf_id`; `firewall_group_ids` (non-empty list of ids) gives `FIREWALL_GROUPS`; `address` and/or `port` give `ADDRESS_AND_PORT` with `invert_address` and `invert_port` always present as booleans (default False). The three families are mutually exclusive. `invert_address` without `address` (or `invert_port` without `port`) is an error.
  - `build_rule(*, description, nat_type, protocol, ip_version, in_interface, out_interface, translated_ip, translated_port, source, destination, exclude, enabled, logging, rule_index) -> dict` returns the body or a validation error.
  - `filter_ports(body: dict) -> bool` (whether either filter or the translated port names a port), used by the protocol check.

- [x] **Step 1: Write the failing tests**

```python
def test_dnat_ntp_redirect_body():
    body = build_rule(description="NTP redirect to resolver-a", nat_type="DNAT", protocol="udp",
        ip_version="IPV4", in_interface="00000000-0000-0000-0000-0000000000d1", out_interface=None,
        translated_ip="192.0.2.53", translated_port="123", source=None,
        destination={"port": "123"}, exclude=False, enabled=True, logging=False, rule_index=2)
    assert body == {"description": "NTP redirect to resolver-a", "type": "DNAT", "protocol": "udp",
        "ip_version": "IPV4", "enabled": True, "exclude": False, "logging": False, "rule_index": 2,
        "in_interface": "00000000-0000-0000-0000-0000000000d1", "ip_address": "192.0.2.53", "port": "123",
        "source_filter": {"filter_type": "NONE"},
        "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "123",
                               "invert_address": False, "invert_port": False}}

def test_exclude_rule_has_no_translation():
    body = build_rule(..., nat_type="DNAT", exclude=True, translated_ip=None, translated_port=None,
                      source={"address": "192.0.2.53"}, destination={"port": "123"}, ...)
    assert body["exclude"] is True and "ip_address" not in body and "port" not in body
    assert body["source_filter"]["address"] == "192.0.2.53"

def test_masquerade_body_uses_out_interface():
    body = build_rule(..., nat_type="MASQUERADE", in_interface=None, out_interface=DEFAULT_ID,
                      source={"address": "192.0.2.0/24"},
                      destination={"address": "192.0.2.53", "port": "123"}, ...)
    assert body["out_interface"] == DEFAULT_ID and "in_interface" not in body and "ip_address" not in body
```

Error tests, one each, asserting `is_error(result)` and a message naming the field:
`test_dnat_requires_in_interface`, `test_dnat_rejects_out_interface`, `test_masquerade_rejects_translated_ip`, `test_snat_requires_translated_ip_unless_exclude`, `test_exclude_rejects_translated_ip`, `test_port_requires_protocol_other_than_all` (filter port and translated port, Edge Case 2), `test_translated_port_rejects_range` (`"8080-8090"`), `test_filter_port_accepts_range` (`"8080-8090"` ok, `"9000-8000"` and `"0"` and `"65536"` rejected), `test_cidr_with_host_bits_rejected` (`"192.0.2.5/24"`, message contains `192.0.2.0/24`, Edge Case 3), `test_address_family_must_match_ip_version` (`"fd00::1"` with `IPV4`), `test_filter_families_are_exclusive` (`address` + `network_id`), `test_unknown_filter_key_rejected`, `test_invert_without_value_rejected`, `test_description_rejects_empty_and_control_chars`, `test_rule_index_must_be_non_negative_int` (`-1`, `True`, `"2"`), `test_enum_fields_validated` (bad `nat_type`, `protocol`, `ip_version`).

- [x] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/unit/test_network_nat_body.py -q`
Expected: FAIL with `ModuleNotFoundError: unifi_mcp.tools.network.nat_body`

- [x] **Step 3: Implement `nat_body.py`**

Use `ipaddress.ip_address` for single addresses and `ipaddress.ip_network(strict=True)` for CIDRs; reuse `validation.validation_error`, `check_id` and `check_enum`. Ports are strings in the body; accept `int` input and convert. Descriptions are at most 128 characters. The module has no `TOOLS`, so give it `TOOLS = []`, `GROUP = "security"` and `TIER2_TOOLS = {}` if the registry requires them for every module under `tools/network` (check `test_registry.py`; `zbf_policy_filters.py` shows the precedent).

- [x] **Step 4: Run them and confirm they pass**

Run: `uv run pytest tests/unit/test_network_nat_body.py -q`
Expected: all pass

- [x] **Step 5: Commit**

```bash
git add src/unifi_mcp/tools/network/nat_body.py tests/unit/test_network_nat_body.py
git commit -m "feat: CLAUD-929 validate and build NAT rule bodies"
```

### Task 2: richer NAT rule output from `list_nat_rules`

**Files:**
- Modify: `src/unifi_mcp/tools/network/routing.py:174-188`
- Create: `tests/fixtures/nat_rules.json`
- Test: `tests/unit/test_network_routing.py`

**Interfaces:**
- Produces: `_format_nat_rule(r: dict) -> dict` (still in `routing.py`) also returns `exclude` (default False), `logging` (default False), `rule_index` (default None) and `is_predefined` (default False); `description` goes through `clean_text`. `nat_rules.py` imports it.

- [x] **Step 1: Write the failing test** `test_list_nat_rules_reports_write_fields`: mock GET `NAT` with `nat_rules.json` (three rules: a user DNAT with `rule_index` 1, a user MASQUERADE with `rule_index` 2 and `exclude: false`, a predefined rule with `is_predefined: true`), assert those four fields on each.
- [x] **Step 2: Run it and confirm it fails** (`KeyError: 'exclude'`).
- [x] **Step 3: Add the four fields to `_format_nat_rule`.**
- [x] **Step 4: Run `uv run pytest tests/unit/test_network_routing.py -q` and confirm it passes.**
- [x] **Step 5: Commit** `feat: CLAUD-929 report exclude, logging, index and predefined on NAT rules`

### Wave 1 checkpoint

- [x] `uv run pytest -q` passes
- [x] Done-when checks verified
- [x] No review (pure code, covered by the Wave 2 review of the combined diff)
- [x] Status line sent to the owner

---

## Wave 2: the five NAT tools work against a mocked console, documented and versioned

**Done when:** all five tools are registered in group `security`, `gen_tool_docs.py --check` reports network 171, the full suite and coverage gate pass, and the code and security reviews have no open CRITICAL or HIGH findings.

### Task 3: `get_nat_rule` and `create_nat_rule`

**Files:**
- Create: `src/unifi_mcp/tools/network/nat_rules.py`
- Test: `tests/unit/test_network_nat_rules.py`

**Interfaces:**
- Consumes: `build_rule`, `is_error` (Task 1); `_format_nat_rule`, `NAT_PATH` (Task 2, `routing.py`); `_preview`, `_executed` (`zbf_official.py`).
- Produces:
  - `GROUP = "security"`, `TIER2_TOOLS = {"create_nat_rule": "routing", "update_nat_rule": "routing", "toggle_nat_rule": "routing", "delete_nat_rule": "routing"}`, `TOOLS` listing all five tools.
  - `async def get_nat_rule(client: UnifiClient, rule_id: str) -> dict` (Tier 1; uncached fetch; `NOT_FOUND` error when absent).
  - `async def create_nat_rule(client, description: str, nat_type: str, protocol: str = "all", ip_version: str = "IPV4", in_interface: str | None = None, out_interface: str | None = None, translated_ip: str | None = None, translated_port: str | int | None = None, source: dict | None = None, destination: dict | None = None, exclude: bool = False, enabled: bool = True, logging: bool = False, rule_index: int | None = None, confirm: bool = False) -> dict`
  - Private helpers later tasks reuse: `_fetch_rules(client) -> list[dict]` (raw, uncached), `_find(rules, rule_id) -> dict | None`, `_check_references(client, body) -> dict | None` (every interface, `network_conf_id` and firewall group id exists), `_verify(client, rule_id, intended: dict) -> dict` (the read-back), `_fingerprint(rule: dict) -> str`, `_remember_preview(tool, rule_id, rule)`, `_changed_since_preview(tool, rule_id, rule) -> dict | None` (same TTL and CONFLICT shape as `zbf_official.py`, with NAT wording).

- [x] **Step 1: Write the failing tests**
  - `test_module_conventions`: `GROUP`, `TIER2_TOOLS` as above, `len(TOOLS) == 5`.
  - `test_get_nat_rule_found` and `test_get_nat_rule_not_found` (category `NOT_FOUND`).
  - `test_create_preview_sends_nothing`: `confirm=False` returns `preview: True`, the built `body`, and an `impact` string; respx asserts no POST was made.
  - `test_create_rejects_unknown_interface`: `in_interface` not in the networkconf fixture gives `VALIDATION_ERROR` naming it, at preview time.
  - `test_create_assigns_next_rule_index`: existing indexes 1 and 2, no `rule_index` given; the POSTed JSON has `rule_index == 3` (Edge Case 4).
  - `test_create_rejects_taken_rule_index`: `rule_index=2` gives `VALIDATION_ERROR`.
  - `test_create_confirm_posts_and_verifies`: POST returns the saved rule with an `_id`; the follow-up GET contains it; result has `executed: True`, `verified: True`, `rule["id"]`; `client.invalidate_cache` called with `"routing"`.
  - `test_create_reports_mismatch`: the follow-up GET returns the rule with `protocol: "tcp_udp"` instead of `"udp"`; result has `verified: False` and `mismatches == {"protocol": {"intended": "udp", "saved": "tcp_udp"}}` (Edge Case 5).
  - `test_create_empty_200_is_not_success`: POST returns `{}`; `executed: False`.
- [x] **Step 2: Run them and confirm they fail** (`ModuleNotFoundError`).
- [x] **Step 3: Implement `get_nat_rule`, `create_nat_rule` and the helpers.** `_verify` compares only the keys of the intended body (nested filters compared key by key), so controller-added keys do not count as mismatches. The created rule is found by the `_id` in the POST response, else by exact `description` when exactly one rule has it, else `verified: False` with a message.
- [x] **Step 4: Run `uv run pytest tests/unit/test_network_nat_rules.py -q` and confirm they pass.**
- [x] **Step 5: Commit** `feat: CLAUD-929 add get_nat_rule and create_nat_rule`

### Task 4: `update_nat_rule`, `toggle_nat_rule`, `delete_nat_rule`  `critical`

**Files:**
- Modify: `src/unifi_mcp/tools/network/nat_rules.py`
- Modify: `src/unifi_mcp/tools/network/nat_body.py` (add `rule_to_args`)
- Test: `tests/unit/test_network_nat_rules.py`, `tests/unit/test_network_nat_body.py`

**Interfaces:**
- Consumes: Task 3 helpers.
- Produces:
  - `rule_to_args(rule: dict) -> dict` in `nat_body.py`: the inverse of `build_rule`, giving the keyword arguments that rebuild the same body (filters back to `spec` dicts).
  - `async def update_nat_rule(client, rule_id: str, description=None, nat_type=None, protocol=None, ip_version=None, in_interface=None, out_interface=None, translated_ip=None, translated_port=None, source=None, destination=None, clear_source: bool = False, clear_destination: bool = False, clear_translated_port: bool = False, exclude=None, enabled=None, logging=None, rule_index=None, confirm: bool = False) -> dict`. A given `source`/`destination` replaces that whole filter; `clear_*` sets it to `NONE` (or drops the port). The PUT body is the fetched rule with the rebuilt body's keys applied, so `_id` and controller-only keys are kept.
  - `async def toggle_nat_rule(client, rule_id: str, enabled: bool, confirm: bool = False) -> dict` (PUT the fetched rule with only `enabled` changed).
  - `async def delete_nat_rule(client, rule_id: str, confirm: bool = False) -> dict` (DELETE, then verify the id is gone).

- [x] **Step 1: Write the failing tests**
  - `test_rule_to_args_round_trips`: for each rule in `nat_rules.json` except the predefined one, `build_rule(**rule_to_args(r))` equals the rule's body keys.
  - `test_update_preview_shows_before_and_after` and sends no PUT.
  - `test_update_merges_unspecified_fields`: only `description` given; the PUT JSON keeps every other field and `_id`.
  - `test_update_type_change_drops_type_specific_fields`: DNAT rule, `nat_type="MASQUERADE", out_interface=ID`; the PUT JSON has no `in_interface`, `ip_address` or `port` (Edge Case 1).
  - `test_update_conflict_when_changed_after_preview`: the second GET returns a different `description`; result category `CONFLICT`, no PUT.
  - `test_update_toggle_delete_refuse_predefined`: each returns `VALIDATION_ERROR` for the predefined rule, at preview.
  - `test_toggle_changes_only_enabled`: PUT JSON equals the fetched rule except `enabled`.
  - `test_delete_confirm_deletes_and_verifies_gone`: DELETE called on `.../nat/{id}`; follow-up GET lacks it; `verified: True`.
  - `test_delete_conflict_when_changed_after_preview`.
  - `test_writes_invalidate_routing_cache` (parametrized over the three tools).
- [x] **Step 2: Run them and confirm they fail.**
- [x] **Step 3: Implement the three tools and `rule_to_args`.** When `nat_type` changes, do not carry `in_interface`, `out_interface`, `ip_address` or `port` over from the current rule; the caller supplies the new ones.
- [x] **Step 4: Run `uv run pytest tests/unit/test_network_nat_rules.py tests/unit/test_network_nat_body.py -q` and confirm they pass.**
- [x] **Step 5: Commit** `feat: CLAUD-929 add update, toggle and delete for NAT rules`
- [x] **Step 6: Review now (`critical`: delete and live traffic changes).** Changed: the review found no CRITICAL or HIGH; MEDIUM 1-3, half of 4 and LOW 3 were fixed in `0f7fe74` (removed-field verification, `changes` lists removals, index check only on a move, exclude rules drop stale translation, invert-only filter is NONE); the rest went to bundle CLAUD-930. `code-reviewer` (sonnet) on `git diff main...HEAD -- src/unifi_mcp/tools/network/nat_*.py`; fix CRITICAL and HIGH findings before Task 5.

### Task 5: docs, counts and version 0.11.0

**Files:** `docs/API.md` (new "NAT Rules (5 tools)" section after Routing, same layout as the Routing section: module, group `security`, tier per tool, parameters, returns), `docs/TOOLS.md` (regenerated), `docs/COMPATIBILITY.md` (NAT row: v2 endpoint, read and write, sources, verified live in Wave 3), `README.md` (category table row "NAT rules | 5 | ..." and the Routing row's note), `CHANGELOG.md` (`## [0.11.0] - <release date>` with Added / Changed / Notes in the v0.10.0 style), `pyproject.toml` (`version = "0.11.0"`), `.claude-plugin/plugin.json` (version and tool total +5), `uv.lock` (`uv lock`).

- [x] **Step 1:** `uv run python scripts/gen_tool_docs.py` then `uv run python scripts/gen_tool_docs.py --check`. Expected: `network 171`.
- [x] **Step 2:** Write the API, README, COMPATIBILITY and CHANGELOG text. The CHANGELOG Notes say what was not verified live yet; Wave 3 updates them.
- [x] **Step 3:** `uv lock` and `uv run pytest -q`. Changed: run `uv sync --all-extras` (as CI does); a plain `uv sync` removes pytest. Expected: all pass, coverage at least 80%.
- [x] **Step 4: Commit** `docs: CLAUD-929 document NAT rule tools and bump to 0.11.0`

### Wave 2 checkpoint

- [x] `uv run pytest -q` and `uv run python scripts/gen_tool_docs.py --check` pass
- [x] Done-when checks verified
- [x] `code-reviewer` (sonnet) on `git diff main...HEAD` (skip files already reviewed in Task 4 Step 6) and `security-reviewer` (inherit) once on the whole diff (the tools change live gateway traffic handling); fix CRITICAL and HIGH. Changed: the security review found one HIGH (IPv6 zone ids let arbitrary text through `address_value`) and one MEDIUM (the tool's preview guard failed open and was keyed by rule id); both fixed in `0bc6e9b`, with the guard now keyed by call parameters and comparing the exact request. The repo is public, so the branch history was rewritten (unpushed) to replace home-LAN values with documentation addresses; real values live in CLAUD-929.
- [x] Status line sent to the owner

---

## Wave 3: verified on the live console, released, and the NTP redirect in place

**Done when:** a disabled test rule was created, read, updated, toggled and deleted through the MCP with `verified: True` at each step; v0.11.0 is merged and tagged; the four NTP rules exist; and the redirect checks in Task 8 pass.

### Task 6: live smoke test with a throwaway rule

- [x] **Step 1:** Point the MCP at the branch checkout (it already is: `~/.claude/scripts/unifi-wrapper.sh` runs `~/Github_Projects/unifi-mcp`) and ask the owner to reconnect the `unifi` server with `/mcp`. Confirm with `get_server_info` and `list_tool_groups` that `create_nat_rule` exists.
- [x] **Step 2:** Preview, then confirm `create_nat_rule(description="unifi-mcp smoke test (delete me)", nat_type="DNAT", protocol="udp", in_interface=<Default id>, translated_ip="192.0.2.53", translated_port=65000, destination={"port": "65000"}, enabled=False)`. Expected: `executed: True`, `verified: True`.
- [x] **Step 3:** `get_nat_rule` on it; save the raw record (ids replaced with placeholders) as `tests/fixtures/nat_rules_live.json` and add `test_live_shape_round_trips` (`rule_to_args` then `build_rule` reproduces its body keys). If the live record has keys or value spellings this plan did not expect, fix `nat_body.py` first and note it in the CHANGELOG.
- [x] **Step 4:** `update_nat_rule(description="unifi-mcp smoke test 2 (delete me)")`, then `toggle_nat_rule(enabled=True)` and `toggle_nat_rule(enabled=False)` (UDP 65000 is unused on this LAN, so enabling it briefly changes nothing). Each `verified: True`. This settles whether PUT accepts the full fetched record.
- [x] **Step 5:** `delete_nat_rule`; `verified: True`; `list_nat_rules` returns `[]` again.
- [x] **Step 6:** Update the CHANGELOG Notes and COMPATIBILITY row with what was verified live. Commit `test: CLAUD-929 pin the live NAT rule shape`.

### Task 7: release v0.11.0

- [ ] **Step 1:** `uv run pytest -q` and `gen_tool_docs.py --check` pass. Push the branch with `-u`, open a PR titled `release v0.11.0: NAT rule tools` (body: summary, live verification evidence, test plan), wait for CI green.
- [ ] **Step 2:** Merge the PR (merge commit, matching `Merge PR #10: release v0.10.0`), tag `v0.11.0` on the merge commit, push the tag, and create the GitHub release from the CHANGELOG section.
- [ ] **Step 3:** `git checkout main && git pull`; the owner reconnects `/mcp`; `get_server_info` shows version 0.11.0.

### Task 8: the LAN NTP redirect  `critical`

Rules on network Default (`in_interface`/`out_interface` = the Default `networkconf` id from `list_networks`), created disabled first, in this order:

| rule_index | Description | Type | Key fields |
|---|---|---|---|
| next | `NTP redirect: exclude resolver-a` | DNAT, `exclude=True` | protocol `udp`, source `{"address": "192.0.2.53"}`, destination `{"port": "123"}` |
| next+1 | `NTP redirect: exclude resolver-b` | DNAT, `exclude=True` | protocol `udp`, source `{"address": "192.0.2.54"}`, destination `{"port": "123"}` |
| next+2 | `NTP redirect to resolver-a` | DNAT | protocol `udp`, destination `{"port": "123"}`, translated `192.0.2.53:123` |
| next+3 | `NTP redirect hairpin` | MASQUERADE | protocol `udp`, source `{"address": "192.0.2.0/24"}`, destination `{"address": "192.0.2.53", "port": "123"}` |

- [ ] **Step 1:** Baseline (already recorded 2026-11-14 19:1x): from the MacBook `sntp -t 3 192.0.2.1` times out; `sntp -t 3 time.google.com` answers.
- [ ] **Step 2:** Show the owner the four previews in one message and get approval; then confirm each with `enabled=False`, each `verified: True`.
- [ ] **Step 3:** Enable the masquerade and the two exclude rules, then the DNAT last (`toggle_nat_rule`).
- [ ] **Step 4: Verify.** Each check must pass:
  - MacBook: `sntp -t 3 192.0.2.1` answers (proves DNAT plus hairpin); `sntp -t 3 time.google.com` answers.
  - resolver-a: `pihole-FTL ntp time.cloudflare.com` gives 8/8 with round-trip delay above 2 ms (a reply from itself would be under 1 ms; proves its exclude rule).
  - resolver-b: the same command, delay above 2 ms (proves its exclude rule; a redirect to Main would be about 1 ms).
- [ ] **Step 5: If a Pi check fails**, the exclude rules are evaluated in the other order: swap the indexes with `update_nat_rule(rule_index=...)` so the excludes sit after or before the DNAT as needed, and re-run Step 4. If any check still fails, roll back with `toggle_nat_rule(<DNAT id>, enabled=False)` and report.
- [ ] **Step 6:** Record the outcome: Jira comment on CLAUD-929 naming the rule ids and the probe output, then move it to Done; update the pihole-control memory and Pi-hole config docs per the owner.

### Wave 3 checkpoint

- [ ] Done-when checks verified with the command output quoted in the status line
- [ ] No further review (code reviewed in Wave 2; Task 8 is configuration verified by probes)
- [ ] Status line sent to the owner

## Open Questions

None. Two controller behaviors are unverified and are settled by live tasks rather than guessed: whether PUT accepts the full fetched record (Task 6 Step 4) and the evaluation order of `rule_index` for exclude rules (Task 8 Step 5).
