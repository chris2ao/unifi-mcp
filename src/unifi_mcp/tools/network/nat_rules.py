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
from unifi_mcp.tools.network.nat_body import build_rule, is_error
from unifi_mcp.tools.network.routing import NAT_PATH, _format_nat_rule
from unifi_mcp.tools.network.zbf_official import _executed, _preview
from unifi_mcp.validation import check_id, validation_error

GROUP = "security"

TIER2_TOOLS = {
    "create_nat_rule": "routing",
}

_CACHE = "routing"
_NETWORKS = "/proxy/network/api/s/{site}/rest/networkconf"
_GROUPS = "/proxy/network/api/s/{site}/rest/firewallgroup"
_PREVIEW_TTL_SECONDS = 600.0
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

def _mismatches(intended: dict, saved: dict) -> dict:
    out: dict = {}
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


async def _verify(client: UnifiClient, rule_id: str | None, intended: dict) -> dict:
    """Read the rule back and compare it with the body that was sent."""
    rule = _locate(await _fetch_rules(client), rule_id, intended.get("description", ""))
    if rule is None:
        return {
            "verified": False,
            "message": "The write returned success but the rule was not found when read back. "
                       "Check list_nat_rules.",
        }
    mismatches = _mismatches(intended, rule)
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
    return {**result, **await _verify(client, _saved_id(response), body)}


TOOLS = [
    get_nat_rule,
    create_nat_rule,
]
