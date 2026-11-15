"""Create, update, toggle and delete gateway NAT rules (DNAT, SNAT, masquerade).

Internal v2 endpoint with no public contract (Network 9.0+):
- GET    /proxy/network/v2/api/site/{site}/nat         (list; there is no GET by id)
- POST   /proxy/network/v2/api/site/{site}/nat
- PUT    /proxy/network/v2/api/site/{site}/nat/{id}
- DELETE /proxy/network/v2/api/site/{site}/nat/{id}

Rule ids are the ``id`` values from ``list_nat_rules`` (group ``insights``).
Interface and network ids are ``id`` values from ``list_networks``; firewall
group ids come from ``list_firewall_groups``. Bodies are validated and built in
nat_body.py.

Rules are evaluated in ``rule_index`` order. ``exclude=True`` takes matching
traffic out of translation, so an exclude rule placed before a broader rule
carves out exceptions (for example, a resolver's own traffic from a redirect).

Every confirmed write reads the rule list back and reports ``verified`` with
any ``mismatches`` between what was sent and what the controller saved.
"""

import hashlib
import json
import time

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.tools.network.nat_body import _present, build_rule, is_error, rule_to_args
from unifi_mcp.tools.network.routing import NAT_PATH, _format_nat_rule
from unifi_mcp.tools.network.zbf_official import _executed, _preview
from unifi_mcp.validation import check_id, validation_error

GROUP = "security"

TIER2_TOOLS = {
    "create_nat_rule": "routing",
    "update_nat_rule": "routing",
    "toggle_nat_rule": "routing",
    "delete_nat_rule": "routing",
}

_CACHE = "routing"
_NETWORKS = "/proxy/network/api/s/{site}/rest/networkconf"
_GROUPS = "/proxy/network/api/s/{site}/rest/firewallgroup"
_PREVIEW_TTL_SECONDS = 600.0
# Body keys that only some rule types (or non-exclude rules) carry. When a body
# leaves one out, the saved rule must not have it either.
_TYPE_SPECIFIC = ("in_interface", "out_interface", "ip_address", "port")
_IMPACT = (
    "Changes how the gateway translates matching traffic as soon as the rule is saved "
    "enabled. A wrong DNAT or masquerade can cut devices off from the service it matches."
)

# Fingerprint of each rule as it was when a preview was shown, keyed by
# (tool, rule_id). Confirm compares against it so a rule edited after its
# preview (in the UI or by another call) is not changed blindly.
_previewed: dict[tuple[str, str], tuple[str, float]] = {}


# --- fetch and lookup ---------------------------------------------------------

def _items(response) -> list[dict]:
    if isinstance(response, dict):
        response = response.get("data", [])
    return [r for r in response or [] if isinstance(r, dict)]


async def _fetch_rules(client: UnifiClient) -> list[dict]:
    """The raw rule list, uncached, so previews and verification see the console's current state."""
    return _items(await client.get(NAT_PATH))


def _find(rules: list[dict], rule_id: str) -> dict | None:
    return next((r for r in rules if r.get("_id") == rule_id), None)


def _not_found(rule_id: str) -> dict:
    return {
        "error": True, "category": "NOT_FOUND",
        "message": f"No NAT rule found with id '{rule_id}'.", "rule_id": rule_id,
    }


def _referenced_ids(body: dict) -> tuple[set[str], set[str]]:
    networks = {body[k] for k in ("in_interface", "out_interface") if body.get(k)}
    groups: set[str] = set()
    for key in ("source_filter", "destination_filter"):
        f = body.get(key) or {}
        if f.get("network_conf_id"):
            networks.add(f["network_conf_id"])
        groups.update(f.get("firewall_group_ids") or [])
    return networks, groups


async def _check_references(client: UnifiClient, body: dict) -> dict | None:
    """VALIDATION_ERROR naming any interface, network or firewall group id that does not exist."""
    networks, groups = _referenced_ids(body)
    for wanted, path, cache, tool in (
        (networks, _NETWORKS, "networks", "list_networks"),
        (groups, _GROUPS, "firewall", "list_firewall_groups"),
    ):
        if not wanted:
            continue
        known = {r.get("_id") for r in _items(await client.get(path, cache_category=cache, cache_ttl=30.0))}
        missing = sorted(wanted - known)
        if missing:
            return validation_error(f"Unknown id(s): {', '.join(missing)}. Use ids from {tool}.")
    return None


# --- preview bookkeeping ------------------------------------------------------

def _fingerprint(rule: dict) -> str:
    return hashlib.sha256(json.dumps(rule, sort_keys=True).encode()).hexdigest()


def _remember_preview(tool: str, rule_id: str, rule: dict) -> None:
    now = time.monotonic()
    for key in [k for k, (_, seen) in _previewed.items() if now - seen > _PREVIEW_TTL_SECONDS]:
        del _previewed[key]
    _previewed[(tool, rule_id)] = (_fingerprint(rule), now)


def _changed_since_preview(tool: str, rule_id: str, rule: dict) -> dict | None:
    """CONFLICT error when the rule differs from what this tool's preview showed."""
    entry = _previewed.pop((tool, rule_id), None)
    if entry is None or entry[0] == _fingerprint(rule):
        return None
    return {
        "error": True, "category": "CONFLICT", "rule_id": rule_id,
        "message": (
            f"NAT rule '{_format_nat_rule(rule)['description']}' changed after it was previewed. "
            "Preview again to see the current rule before confirming."
        ),
    }


# --- verification -------------------------------------------------------------

def _absent_keys(body: dict) -> tuple[str, ...]:
    return tuple(k for k in _TYPE_SPECIFIC if k not in body)


def _mismatches(intended: dict, saved: dict, absent: tuple[str, ...] = ()) -> dict:
    """Keys whose saved value differs from the intended one, plus absent keys the console still holds."""
    out: dict = {k: {"intended": None, "saved": saved[k]} for k in absent if _present(saved.get(k)) is not None}
    for key, want in intended.items():
        have = saved.get(key)
        if isinstance(want, dict):
            have = have if isinstance(have, dict) else {}
            for sub, sub_want in want.items():
                if have.get(sub) != sub_want:
                    out[f"{key}.{sub}"] = {"intended": sub_want, "saved": have.get(sub)}
        elif have != want:
            out[key] = {"intended": want, "saved": have}
    return out


def _saved_id(response) -> str | None:
    if isinstance(response, dict) and "data" in response:
        response = response["data"]
    if isinstance(response, list):
        response = response[0] if response else {}
    return response.get("_id") if isinstance(response, dict) else None


def _locate(rules: list[dict], rule_id: str | None, description: str) -> dict | None:
    if rule_id:
        return _find(rules, rule_id)
    same = [r for r in rules if r.get("description") == description]
    return same[0] if len(same) == 1 else None


async def _verify(client: UnifiClient, rule_id: str | None, intended: dict,
                  absent: tuple[str, ...] = ()) -> dict:
    """Read the rule back and compare it with what was sent; ``absent`` keys must be gone."""
    rule = _locate(await _fetch_rules(client), rule_id, intended.get("description", ""))
    if rule is None:
        return {
            "verified": False,
            "message": "The write returned success but the rule was not found when read back. "
                       "Check list_nat_rules.",
        }
    mismatches = _mismatches(intended, rule, absent)
    out = {"rule": _format_nat_rule(rule), "verified": not mismatches}
    if mismatches:
        out["mismatches"] = mismatches
        out["message"] = "The console saved the rule with different values; see mismatches."
    return out


# --- tools --------------------------------------------------------------------

async def get_nat_rule(client: UnifiClient, rule_id: str) -> dict:
    """Get one NAT rule by id (from list_nat_rules), read fresh from the console."""
    error = check_id(rule_id, "rule_id")
    if error:
        return error
    rule = _find(await _fetch_rules(client), rule_id)
    return _format_nat_rule(rule) if rule else _not_found(rule_id)


def _assign_index(body: dict, rules: list[dict]) -> dict:
    taken = {r.get("rule_index") for r in rules if isinstance(r.get("rule_index"), int)}
    if "rule_index" in body:
        if body["rule_index"] in taken:
            return validation_error(
                f"rule_index {body['rule_index']} is already used. Taken: {sorted(taken)}. "
                "Pick a free index or omit it to append."
            )
        return body
    return {**body, "rule_index": max(taken) + 1 if taken else 0}


async def create_nat_rule(
    client: UnifiClient,
    description: str,
    nat_type: str,
    protocol: str = "all",
    ip_version: str = "IPV4",
    in_interface: str | None = None,
    out_interface: str | None = None,
    translated_ip: str | None = None,
    translated_port: str | int | None = None,
    source: dict | None = None,
    destination: dict | None = None,
    exclude: bool = False,
    enabled: bool = True,
    logging: bool = False,
    rule_index: int | None = None,
    confirm: bool = False,
) -> dict:
    """Create a NAT rule. Preview first (confirm=False), then confirm=True.

    nat_type: DNAT (matches traffic arriving on in_interface; rewrites the
    destination to translated_ip[:translated_port]), SNAT (leaving on
    out_interface; rewrites the source to translated_ip) or MASQUERADE
    (leaving on out_interface; rewrites the source to the interface address).
    Interfaces are network ids from list_networks.
    protocol: all, tcp, udp or tcp_udp (ports need one of the last three).
    source / destination: {"address": IP or CIDR, "port": "123" or "8000-8010",
    "invert_address": bool, "invert_port": bool}, or {"network_id": id}, or
    {"firewall_group_ids": [ids]}; omit to match everything.
    exclude=True makes an exception: matching traffic is not translated
    (omit translated_ip/port). Rules apply in rule_index order; omit it to
    append after the existing rules.
    """
    body = build_rule(
        description=description, nat_type=nat_type, protocol=protocol, ip_version=ip_version,
        in_interface=in_interface, out_interface=out_interface, translated_ip=translated_ip,
        translated_port=translated_port, source=source, destination=destination,
        exclude=exclude, enabled=enabled, logging=logging, rule_index=rule_index,
    )
    if is_error(body):
        return body
    body = _assign_index(body, await _fetch_rules(client))
    if is_error(body):
        return body
    error = await _check_references(client, body)
    if error:
        return error
    if not confirm:
        return _preview(
            "create_nat_rule",
            f"Will create {nat_type} rule '{description}' at rule_index {body['rule_index']} "
            f"(enabled={enabled}). Call again with confirm=True to execute.",
            _IMPACT, body=body,
        )
    response = await client.post(NAT_PATH, json=body)
    client.invalidate_cache(_CACHE)
    result = _executed("create_nat_rule", response)
    if not result["executed"]:
        return result
    return {**result, **await _verify(client, _saved_id(response), body, _absent_keys(body))}


# --- existing rules -------------------------------------------------------------


async def _load_editable(client: UnifiClient, rule_id: str, verb: str) -> tuple[dict | None, dict | None]:
    """(rule, None) for a user-defined rule, else (None, error)."""
    error = check_id(rule_id, "rule_id")
    if error:
        return None, error
    rule = _find(await _fetch_rules(client), rule_id)
    if rule is None:
        return None, _not_found(rule_id)
    if rule.get("is_predefined"):
        return None, validation_error(
            f"NAT rule '{_format_nat_rule(rule)['description']}' is predefined by the console and "
            f"cannot be {verb}."
        )
    return rule, None


def _changes(before: dict, after: dict, keys) -> dict:
    """What the update changes, including removed fields and filter sub-keys."""
    out: dict = {}
    for key in keys:
        old, new = before.get(key), after.get(key)
        if isinstance(old, dict) or isinstance(new, dict):
            old, new = old if isinstance(old, dict) else {}, new if isinstance(new, dict) else {}
            for sub in sorted(set(old) | set(new)):
                if _present(old.get(sub)) != _present(new.get(sub)):
                    out[f"{key}.{sub}"] = {"from": _present(old.get(sub)), "to": _present(new.get(sub))}
        elif _present(old) != _present(new):
            out[key] = {"from": _present(old), "to": _present(new)}
    return out


async def _put(client: UnifiClient, tool: str, rule_id: str, record: dict, intended: dict,
               absent: tuple[str, ...] = ()) -> dict:
    response = await client.put(f"{NAT_PATH}/{rule_id}", json=record)
    client.invalidate_cache(_CACHE)
    result = _executed(tool, response, rule_id=rule_id)
    if not result["executed"]:
        return result
    return {**result, **await _verify(client, rule_id, intended, absent)}


def _merge_args(current: dict, given: dict, clears: dict) -> dict:
    """Overlay the caller's values on the current rule's arguments, or return an error."""
    args = rule_to_args(current)
    if is_error(args):
        return args
    for side in ("source", "destination"):
        if clears[f"clear_{side}"] and given[side] is not None:
            return validation_error(f"Pass {side} or clear_{side}, not both.")
    if clears["clear_translated_port"] and given["translated_port"] is not None:
        return validation_error("Pass translated_port or clear_translated_port, not both.")
    if given["nat_type"] is not None and given["nat_type"] != current.get("type"):
        args.update(in_interface=None, out_interface=None, translated_ip=None, translated_port=None)
    if given["exclude"] is True and given["translated_ip"] is None:
        args.update(translated_ip=None, translated_port=None)
    args.update({k: v for k, v in given.items() if v is not None})
    for key in ("source", "destination", "translated_port"):
        if clears[f"clear_{key}"]:
            args[key] = None
    return args


def _check_index_free(rule_index, rule_id: str, rules: list[dict]) -> dict | None:
    if rule_index is None:
        return None
    owner = next((r for r in rules if r.get("rule_index") == rule_index), None)
    if owner is not None and owner.get("_id") != rule_id:
        return validation_error(
            f"rule_index {rule_index} is used by '{_format_nat_rule(owner)['description']}'. Pick a free index."
        )
    return None


def _updated_record(current: dict, body: dict) -> dict:
    record = {k: v for k, v in current.items() if k not in _TYPE_SPECIFIC or k in body}
    return {**record, **body}


async def update_nat_rule(
    client: UnifiClient,
    rule_id: str,
    description: str | None = None,
    nat_type: str | None = None,
    protocol: str | None = None,
    ip_version: str | None = None,
    in_interface: str | None = None,
    out_interface: str | None = None,
    translated_ip: str | None = None,
    translated_port: str | int | None = None,
    source: dict | None = None,
    destination: dict | None = None,
    clear_source: bool = False,
    clear_destination: bool = False,
    clear_translated_port: bool = False,
    exclude: bool | None = None,
    enabled: bool | None = None,
    logging: bool | None = None,
    rule_index: int | None = None,
    confirm: bool = False,
) -> dict:
    """Update a user-defined NAT rule. Only the fields you pass change. Preview first.

    A given source or destination replaces that whole filter; clear_source /
    clear_destination match everything again; clear_translated_port drops the
    port rewrite. Changing nat_type drops the old interface and translation, so
    pass the new ones. Setting exclude=True drops the translation. The merged
    rule is validated like create_nat_rule. Refused with CONFLICT if the rule
    changed after the preview.
    """
    clears = {"clear_source": clear_source, "clear_destination": clear_destination,
              "clear_translated_port": clear_translated_port}
    for name, value in clears.items():
        if not isinstance(value, bool):
            return validation_error(f"{name} must be a boolean.")
    given = {"description": description, "nat_type": nat_type, "protocol": protocol,
             "ip_version": ip_version, "in_interface": in_interface, "out_interface": out_interface,
             "translated_ip": translated_ip, "translated_port": translated_port, "source": source,
             "destination": destination, "exclude": exclude, "enabled": enabled, "logging": logging,
             "rule_index": rule_index}
    current, error = await _load_editable(client, rule_id, "updated")
    if error:
        return error
    moved = rule_index if rule_index is not None and rule_index != current.get("rule_index") else None
    return await _apply_update(client, rule_id, current, _merge_args(current, given, clears), moved, confirm)


async def _apply_update(client: UnifiClient, rule_id: str, current: dict, args: dict,
                        moved_to: int | None, confirm: bool) -> dict:
    if is_error(args):
        return args
    body = build_rule(**args)
    if is_error(body):
        return body
    error = _check_index_free(moved_to, rule_id, await _fetch_rules(client))
    error = error or await _check_references(client, body)
    if error:
        return error
    record = _updated_record(current, body)
    if not confirm:
        _remember_preview("update_nat_rule", rule_id, current)
        return _preview(
            "update_nat_rule", f"Will update NAT rule {rule_id}. Call again with confirm=True to execute.",
            _IMPACT, rule_id=rule_id, before=_format_nat_rule(current), after=_format_nat_rule(record),
            changes=_changes(current, record, sorted(set(body) | set(_TYPE_SPECIFIC))),
        )
    conflict = _changed_since_preview("update_nat_rule", rule_id, current)
    if conflict:
        return conflict
    return await _put(client, "update_nat_rule", rule_id, record, body, _absent_keys(body))


async def toggle_nat_rule(client: UnifiClient, rule_id: str, enabled: bool, confirm: bool = False) -> dict:
    """Enable or disable a user-defined NAT rule without changing anything else. Preview first."""
    if not isinstance(enabled, bool):
        return validation_error("enabled must be a boolean.")
    current, error = await _load_editable(client, rule_id, "toggled")
    if error:
        return error
    if not confirm:
        _remember_preview("toggle_nat_rule", rule_id, current)
        return _preview(
            "toggle_nat_rule",
            f"Will set NAT rule '{_format_nat_rule(current)['description']}' enabled={enabled}. "
            "Call again with confirm=True to execute.",
            _IMPACT, rule_id=rule_id, enabled=enabled,
        )
    conflict = _changed_since_preview("toggle_nat_rule", rule_id, current)
    if conflict:
        return conflict
    return await _put(client, "toggle_nat_rule", rule_id, {**current, "enabled": enabled}, {"enabled": enabled})


async def delete_nat_rule(client: UnifiClient, rule_id: str, confirm: bool = False) -> dict:
    """Delete a user-defined NAT rule. Irreversible; preview first."""
    current, error = await _load_editable(client, rule_id, "deleted")
    if error:
        return error
    if not confirm:
        _remember_preview("delete_nat_rule", rule_id, current)
        return _preview(
            "delete_nat_rule",
            f"Will delete NAT rule '{_format_nat_rule(current)['description']}'. This is irreversible. "
            "Call again with confirm=True to execute.",
            _IMPACT, rule_id=rule_id, rule=_format_nat_rule(current),
        )
    conflict = _changed_since_preview("delete_nat_rule", rule_id, current)
    if conflict:
        return conflict
    response = await client.delete(f"{NAT_PATH}/{rule_id}")
    client.invalidate_cache(_CACHE)
    result = _executed("delete_nat_rule", response, expect_body=False, rule_id=rule_id)
    if _find(await _fetch_rules(client), rule_id) is None:
        return {**result, "verified": True}
    return {**result, "verified": False,
            "message": "The delete returned success but the rule is still listed. Check list_nat_rules."}


TOOLS = [
    get_nat_rule,
    create_nat_rule,
    update_nat_rule,
    toggle_nat_rule,
    delete_nat_rule,
]
