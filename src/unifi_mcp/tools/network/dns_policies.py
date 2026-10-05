"""DNS Policy tools: list, get, create, update, delete (Network Integration API).

Endpoints (base /proxy/network/integration/v1/sites/{site_id}):
- GET/POST        /dns/policies
- GET/PUT/DELETE  /dns/policies/{dnsPolicyId}

DNS policies are gateway-side local DNS records and conditional forwarders.
Seven types exist, each with a fixed set of required fields (all fields below
are required by the official spec):

- A_RECORD:        domain, ipv4Address, ttlSeconds (0-86400)
- AAAA_RECORD:     domain, ipv6Address, ttlSeconds (0-86400)
- CNAME_RECORD:    domain, targetDomain, ttlSeconds (0-604800)
- MX_RECORD:       domain, mailServerDomain, priority (0-65535)
- TXT_RECORD:      domain, text (1-1024 chars)
- SRV_RECORD:      domain, serverDomain, service, protocol, port, priority, weight
- FORWARD_DOMAIN:  domain, ipAddress (IPv4 or IPv6 DNS server)

PUT replaces the whole policy, so update_dns_policy reads the current policy,
merges the changes and sends the full body.
"""

import ipaddress
import re
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import check_enum, check_id, validation_error

GROUP = "security"
TIER2_TOOLS: dict[str, str] = {
    "create_dns_policy": "dns",
    "update_dns_policy": "dns",
    "delete_dns_policy": "dns",
}

BASE_PATH = "/proxy/network/integration/v1/sites/{site_id}/dns/policies"
DEFAULT_TTL = 14400
DNS_TYPES = (
    "A_RECORD", "AAAA_RECORD", "CNAME_RECORD", "MX_RECORD",
    "TXT_RECORD", "SRV_RECORD", "FORWARD_DOMAIN",
)

# type -> required value fields (besides type and enabled), per the spec.
_TYPE_FIELDS: dict[str, tuple[str, ...]] = {
    "A_RECORD": ("domain", "ipv4Address", "ttlSeconds"),
    "AAAA_RECORD": ("domain", "ipv6Address", "ttlSeconds"),
    "CNAME_RECORD": ("domain", "targetDomain", "ttlSeconds"),
    "MX_RECORD": ("domain", "mailServerDomain", "priority"),
    "TXT_RECORD": ("domain", "text"),
    "SRV_RECORD": ("domain", "serverDomain", "service", "protocol", "port", "priority", "weight"),
    "FORWARD_DOMAIN": ("domain", "ipAddress"),
}
_TTL_MAX = {"A_RECORD": 86400, "AAAA_RECORD": 86400, "CNAME_RECORD": 604800}
_DOMAIN_FIELDS = ("domain", "targetDomain", "mailServerDomain", "serverDomain")
_INT_FIELDS = ("priority", "port", "weight")
_READ_ONLY_KEYS = ("id", "metadata")
_SNAKE_TO_CAMEL = {
    "ipv4_address": "ipv4Address", "ipv6_address": "ipv6Address",
    "ip_address": "ipAddress", "ttl_seconds": "ttlSeconds", "ttl": "ttlSeconds",
    "target_domain": "targetDomain", "mail_server_domain": "mailServerDomain",
    "server_domain": "serverDomain",
}
_LABEL_RE = re.compile(r"[A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?")
_SRV_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,63}")


def _check_domain(value: Any, field: str) -> dict | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 127:
        return validation_error(f"{field} must be a string of 1 to 127 characters.")
    host = value[2:] if value.startswith("*.") else value
    labels = host.rstrip(".").split(".")
    if not all(_LABEL_RE.fullmatch(label) for label in labels):
        return validation_error(
            f"{field} must be a valid DNS name (letters, digits, '-', '_', dot-separated, "
            f"optional leading '*.'). Got: {value!r}."
        )
    return None


def _check_ip(value: Any, field: str, version: int | None) -> dict | None:
    try:
        if not isinstance(value, str):
            raise ValueError
        addr = ipaddress.ip_address(value)
    except ValueError:
        kind = {4: "IPv4", 6: "IPv6"}.get(version, "IPv4 or IPv6")
        return validation_error(f"{field} must be a valid {kind} address. Got: {value!r}.")
    if version and addr.version != version:
        return validation_error(f"{field} must be an IPv{version} address. Got: {value!r}.")
    return None


def _check_int(value: Any, lo: int, hi: int, field: str) -> dict | None:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        return validation_error(f"{field} must be an integer between {lo} and {hi}. Got: {value!r}.")
    return None


def _check_text(value: Any) -> dict | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        return validation_error("text must be a string of 1 to 1024 characters.")
    return None


def _check_srv_name(value: Any, field: str) -> dict | None:
    if not isinstance(value, str) or not _SRV_NAME_RE.fullmatch(value):
        return validation_error(
            f"{field} must be 1-63 characters of letters, digits, '_', '-' or '.' "
            f"(for example '_ldap' or '_tcp'). Got: {value!r}."
        )
    return None


def _check_field(dns_type: str, field: str, value: Any) -> dict | None:
    if field in _DOMAIN_FIELDS:
        return _check_domain(value, field)
    if field == "ipv4Address":
        return _check_ip(value, field, 4)
    if field == "ipv6Address":
        return _check_ip(value, field, 6)
    if field == "ipAddress":
        return _check_ip(value, field, None)
    if field == "ttlSeconds":
        return _check_int(value, 0, _TTL_MAX[dns_type], field)
    if field in _INT_FIELDS:
        return _check_int(value, 0, 65535, field)
    if field == "text":
        return _check_text(value)
    return _check_srv_name(value, field)  # service, protocol


def validate_policy_body(body: dict) -> dict | None:
    """Validate a full create/update body against the per-type spec rules."""
    dns_type = body.get("type")
    err = check_enum(dns_type, DNS_TYPES, "type")
    if err:
        return err
    if not isinstance(body.get("enabled"), bool):
        return validation_error("enabled must be a boolean.")
    fields = _TYPE_FIELDS[dns_type]
    missing = [f for f in fields if body.get(f) is None]
    if missing:
        return validation_error(f"{dns_type} requires: {', '.join(missing)}.")
    extra = sorted(set(body) - set(fields) - {"type", "enabled"})
    if extra:
        return validation_error(
            f"{dns_type} does not accept: {', '.join(extra)}. Allowed value fields: {', '.join(fields)}."
        )
    for field in fields:
        err = _check_field(dns_type, field, body[field])
        if err:
            return err
    return None


def _items(response: Any) -> list:
    if isinstance(response, list):
        return response
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        return response["data"]
    return []


def _unwrap(response: Any) -> dict:
    """Return the single policy object from a bare object or {"data": [obj]}."""
    if isinstance(response, dict) and "data" in response:
        data = response["data"]
        response = data[0] if isinstance(data, list) and data else data
    return response if isinstance(response, dict) else {}


def _format_policy(p: dict) -> dict:
    """Pass through spec fields, flattening metadata.origin."""
    out = {k: v for k, v in p.items() if k != "metadata"}
    out["id"] = p.get("id", "")
    out["origin"] = (p.get("metadata") or {}).get("origin", "")
    return out


def _not_found(policy_id: str) -> dict:
    return {
        "error": True, "category": "NOT_FOUND",
        "message": f"No DNS policy found with id '{policy_id}'", "policy_id": policy_id,
    }


async def _fetch(client: UnifiClient, policy_id: str) -> dict | None:
    """GET one policy (uncached so merges see current state); None when missing."""
    try:
        response = await client.get(f"{BASE_PATH}/{policy_id}")
    except UnifiError as e:
        if e.category == ErrorCategory.NOT_FOUND:
            return None
        raise
    policy = _unwrap(response)
    return policy or None


def _filter_expression(dns_type: str | None, extra: str | None) -> str | None:
    parts = [p for p in (f"type.eq('{dns_type}')" if dns_type else None, extra) if p]
    if len(parts) > 1:
        return f"and({', '.join(parts)})"
    return parts[0] if parts else None


async def list_dns_policies(
    client: UnifiClient, type: str | None = None, filter: str | None = None,  # noqa: A002
) -> list[dict] | dict:
    """List DNS policies (local DNS records and domain forwarders) on the gateway.

    Optional ``type`` is one of A_RECORD, AAAA_RECORD, CNAME_RECORD, MX_RECORD,
    TXT_RECORD, SRV_RECORD, FORWARD_DOMAIN. Optional ``filter`` is an official
    filter expression such as ``domain.like('*.example.com')``; filterable
    properties: type, id, enabled, domain, ipv4Address, ipv6Address,
    targetDomain, mailServerDomain, text, serverDomain, ipAddress, ttlSeconds,
    priority, service, protocol, port, weight. Follows pagination.
    """
    if type is not None:
        err = check_enum(type, DNS_TYPES, "type")
        if err:
            return err
    policies = await client.get_all_pages(
        BASE_PATH, filter=_filter_expression(type, filter),
        cache_category="dns", cache_ttl=30.0,
    )
    return [_format_policy(p) for p in policies if isinstance(p, dict)]


async def get_dns_policy(client: UnifiClient, policy_id: str) -> dict:
    """Get one DNS policy by its UUID, including all type-specific fields and ttl."""
    err = check_id(policy_id, "policy_id")
    if err:
        return err
    policy = await _fetch(client, policy_id)
    return _format_policy(policy) if policy else _not_found(policy_id)


def _executed(action: str, response: Any, **extra: Any) -> dict:
    """Wrap a write result; an empty body on create/update is a silent no-op."""
    if not response or response == {"data": []}:
        return {
            "executed": False, "action": action, **extra, "response": response,
            "message": "The console returned an empty response, so the change was probably not applied. "
                       "Re-read the policy to verify.",
        }
    return {"executed": True, "action": action, **extra, "response": response}


def _build_create_body(
    dns_type: str, enabled: bool, domain: Any, values: dict[str, Any],
) -> dict:
    body = {"type": dns_type, "enabled": enabled, "domain": domain}
    body.update({k: v for k, v in values.items() if v is not None})
    if dns_type in _TTL_MAX and body.get("ttlSeconds") is None:
        body["ttlSeconds"] = DEFAULT_TTL
    return body


async def create_dns_policy(
    client: UnifiClient,
    type: str,
    domain: str,
    ipv4_address: str | None = None,
    ipv6_address: str | None = None,
    target_domain: str | None = None,
    mail_server_domain: str | None = None,
    text: str | None = None,
    server_domain: str | None = None,
    service: str | None = None,
    protocol: str | None = None,
    port: int | None = None,
    priority: int | None = None,
    weight: int | None = None,
    ip_address: str | None = None,
    ttl_seconds: int | None = None,
    enabled: bool = True,
    confirm: bool = False,
) -> dict:
    """Create a DNS policy (local record or domain forwarder). Requires confirm=True after previewing.

    Pass ``type`` plus only the fields for that type. A_RECORD: ipv4_address,
    ttl_seconds. AAAA_RECORD: ipv6_address, ttl_seconds. CNAME_RECORD:
    target_domain, ttl_seconds. MX_RECORD: mail_server_domain, priority.
    TXT_RECORD: text. SRV_RECORD: server_domain, service (e.g. '_ldap'),
    protocol (e.g. '_tcp'), port, priority, weight. FORWARD_DOMAIN: ip_address
    of the DNS server queries for the domain are forwarded to. ttl_seconds
    (A/AAAA up to 86400, CNAME up to 604800) defaults to 14400.
    """
    values = {
        "ipv4Address": ipv4_address, "ipv6Address": ipv6_address,
        "targetDomain": target_domain, "mailServerDomain": mail_server_domain,
        "text": text, "serverDomain": server_domain, "service": service,
        "protocol": protocol, "port": port, "priority": priority,
        "weight": weight, "ipAddress": ip_address, "ttlSeconds": ttl_seconds,
    }
    body = _build_create_body(type, enabled, domain, values)
    err = validate_policy_body(body)
    if err:
        return err
    if not confirm:
        return {
            "preview": True, "action": "create_dns_policy", "policy": body,
            "message": f"Will create {type} DNS policy for '{domain}'. "
                       "Call again with confirm=True to execute.",
        }
    response = await client.post(BASE_PATH, json=body)
    client.invalidate_cache("dns")
    return _executed("create_dns_policy", response)


def _normalize_updates(updates: Any) -> dict | None:
    if not isinstance(updates, dict) or not updates:
        return None
    return {_SNAKE_TO_CAMEL.get(k, k): v for k, v in updates.items()}


async def update_dns_policy(
    client: UnifiClient, policy_id: str, updates: dict, confirm: bool = False,
) -> dict:
    """Update fields of an existing DNS policy. Requires confirm=True after previewing.

    ``updates`` holds only the fields to change, using API names (domain,
    ipv4Address, ttlSeconds, enabled, ...); snake_case such as ttl_seconds is
    accepted. The policy type cannot be changed. The current policy is read,
    merged with ``updates`` and the full body is sent, because PUT replaces
    the policy.
    """
    err = check_id(policy_id, "policy_id")
    if err:
        return err
    changes = _normalize_updates(updates)
    if changes is None:
        return validation_error("updates must be a non-empty object of fields to change.")
    forbidden = [k for k in ("type", *_READ_ONLY_KEYS) if k in changes]
    if forbidden:
        return validation_error(f"updates cannot change: {', '.join(forbidden)}.")
    current = await _fetch(client, policy_id)
    if current is None:
        return _not_found(policy_id)
    # Keep only fields the type accepts, so a field a later firmware adds to the
    # response cannot make every update fail validation.
    keep = {"type", "enabled", *_TYPE_FIELDS.get(current.get("type"), ())}
    base = {k: v for k, v in current.items() if k in keep}
    body = {**base, **changes}
    err = validate_policy_body(body)
    if err:
        return err
    if not confirm:
        return {
            "preview": True, "action": "update_dns_policy", "policy_id": policy_id,
            "current": base, "policy": body,
            "message": f"Will update DNS policy {policy_id}. Call again with confirm=True to execute.",
        }
    response = await client.put(f"{BASE_PATH}/{policy_id}", json=body)
    client.invalidate_cache("dns")
    return _executed("update_dns_policy", response, policy_id=policy_id)


async def delete_dns_policy(
    client: UnifiClient, policy_id: str, confirm: bool = False,
) -> dict:
    """Delete a DNS policy by UUID. Requires confirm=True after previewing."""
    err = check_id(policy_id, "policy_id")
    if err:
        return err
    if not confirm:
        current = await _fetch(client, policy_id)
        if current is None:
            return _not_found(policy_id)
        return {
            "preview": True, "action": "delete_dns_policy", "policy_id": policy_id,
            "policy": _format_policy(current),
            "message": f"Will delete DNS policy {policy_id}. Clients will stop resolving "
                       "it via the gateway. Call again with confirm=True to execute.",
        }
    response = await client.delete(f"{BASE_PATH}/{policy_id}")
    client.invalidate_cache("dns")
    return {"executed": True, "action": "delete_dns_policy", "policy_id": policy_id, "response": response}


TOOLS = [
    list_dns_policies,
    get_dns_policy,
    create_dns_policy,
    update_dns_policy,
    delete_dns_policy,
]
