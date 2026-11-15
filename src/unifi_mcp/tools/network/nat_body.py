"""Validation and body building for gateway NAT rules (v2 ``/nat`` endpoint).

Pure functions, no HTTP. ``build_rule`` turns tool arguments into the body the
controller stores; ``rule_to_args`` turns a stored rule back into arguments so
an update can merge changes and rebuild a fully validated body.

Body keys follow ubiquiti-community/unifi-api ``cmd/fields/custom/Nat.json``
and terraform-provider-unifi ``unifi/nat_resource.go``:

- ``type`` DNAT, SNAT or MASQUERADE. DNAT matches traffic arriving on
  ``in_interface``; SNAT and MASQUERADE match traffic leaving on
  ``out_interface``. Both are network ids (``list_networks``).
- ``ip_address`` / ``port`` are the translated address and port. MASQUERADE
  uses the outgoing interface's address and takes neither. ``port`` is a
  single port; ranges are only accepted in filters.
- ``exclude`` takes matching traffic out of translation (no ``ip_address``).
- ``source_filter`` / ``destination_filter`` match by address and/or port,
  by network, or by firewall groups.
"""

import ipaddress
from typing import Any

from unifi_mcp.validation import check_enum, check_id, clean_text, validation_error

NAT_TYPES = ("DNAT", "SNAT", "MASQUERADE")
PROTOCOLS = ("all", "tcp", "udp", "tcp_udp")
IP_VERSIONS = ("IPV4", "IPV6")
FILTER_KEYS = ("address", "port", "invert_address", "invert_port", "network_id", "firewall_group_ids")
MAX_DESCRIPTION = 128

_NONE_FILTER = {"filter_type": "NONE"}
_IP_VERSION_OF = {4: "IPV4", 6: "IPV6"}


def is_error(value: Any) -> bool:
    """True for a VALIDATION_ERROR-style dict."""
    return isinstance(value, dict) and value.get("error") is True


def _first_error(*values: Any) -> dict | None:
    return next((v for v in values if is_error(v)), None)


# --- scalar checks ----------------------------------------------------------

def _check_bool(value: Any, field: str) -> dict | None:
    return None if isinstance(value, bool) else validation_error(f"{field} must be a boolean.")


def _check_description(value: Any) -> dict | None:
    if not isinstance(value, str) or not value.strip():
        return validation_error("description must be a non-empty string.")
    if not value.isprintable():
        return validation_error("description must not contain control characters (such as newlines).")
    if len(value) > MAX_DESCRIPTION:
        return validation_error(f"description must be at most {MAX_DESCRIPTION} characters.")
    return None


def _check_rule_index(value: Any) -> dict | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return validation_error(f"rule_index must be a non-negative integer. Got: {value!r}.")
    return None


def _parse_port(value: Any) -> int | None:
    """A single port 1-65535 from an int or a plain digit string, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        number = int(value)
    else:
        return None
    return number if 1 <= number <= 65535 else None


def port_value(value: Any, field: str, allow_range: bool) -> str | dict:
    """Normalize a port (or 'low-high' range when allowed) to a string, or return an error."""
    if allow_range and isinstance(value, str) and value.count("-") == 1:
        low, high = (_parse_port(part) for part in value.split("-"))
        if low is not None and high is not None and low <= high:
            return f"{low}-{high}"
    else:
        number = _parse_port(value)
        if number is not None:
            return str(number)
    shape = "a port 1-65535 or a range like '8080-8090'" if allow_range else "a single port 1-65535"
    return validation_error(f"{field} must be {shape}. Got: {value!r}.")


def address_value(value: Any, field: str, ip_version: str, allow_cidr: bool) -> str | dict:
    """Normalize an IP address (or CIDR when allowed) of the given IP version, or return an error."""
    if not isinstance(value, str):
        return validation_error(f"{field} must be an IP address string. Got: {value!r}.")
    if "%" in value or not value.isascii():
        # ipaddress keeps an IPv6 zone id ('%eth0') verbatim, which would let any text
        # through to the gateway as an address.
        return validation_error(
            f"{field} must be a plain IP address or CIDR in ASCII, without a zone id such as '%eth0'. "
            f"Got: {clean_text(value, 64)!r}."
        )
    kind = "an IP address or CIDR" if allow_cidr else "a single IP address"
    try:
        if "/" in value:
            if not allow_cidr:
                return validation_error(f"{field} must be {kind}, not a CIDR. Got: {value!r}.")
            parsed = ipaddress.ip_network(value, strict=True)
        else:
            parsed = ipaddress.ip_address(value)
    except ValueError:
        return _address_error(value, field, kind)
    if _IP_VERSION_OF[parsed.version] != ip_version:
        return validation_error(f"{field} {value!r} is not an {ip_version} address; set ip_version to match.")
    return str(parsed)


def _address_error(value: str, field: str, kind: str) -> dict:
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return validation_error(f"{field} must be {kind}. Got: {value!r}.")
    return validation_error(f"{field} {value!r} has host bits set; did you mean {network}?")


# --- filters ----------------------------------------------------------------

def build_filter(side: str, spec: Any, ip_version: str) -> dict:
    """Build a source or destination filter from a spec dict, or return an error.

    Spec keys: address, port, invert_address, invert_port (ADDRESS_AND_PORT),
    network_id (NETWORK_CONF) or firewall_group_ids (FIREWALL_GROUPS). The
    three families are mutually exclusive. None or {} matches everything.
    """
    if spec is None or spec == {}:
        return dict(_NONE_FILTER)
    if not isinstance(spec, dict):
        return validation_error(f"{side} must be a dict with keys {', '.join(FILTER_KEYS)}.")
    unknown = sorted(set(spec) - set(FILTER_KEYS))
    if unknown:
        return validation_error(f"{side} has unknown keys: {', '.join(unknown)}. Allowed: {', '.join(FILTER_KEYS)}.")
    families = [name for name, keys in (
        ("address/port", ("address", "port", "invert_address", "invert_port")),
        ("network_id", ("network_id",)),
        ("firewall_group_ids", ("firewall_group_ids",)),
    ) if any(k in spec for k in keys)]
    if len(families) > 1:
        return validation_error(f"{side} can match by only one of address/port, network_id or "
                                f"firewall_group_ids. Got: {', '.join(families)}.")
    if "network_id" in spec:
        error = check_id(spec["network_id"], f"{side}.network_id")
        return error or {"filter_type": "NETWORK_CONF", "network_conf_id": spec["network_id"]}
    if "firewall_group_ids" in spec:
        return _group_filter(side, spec["firewall_group_ids"])
    return _address_port_filter(side, spec, ip_version)


def _group_filter(side: str, ids: Any) -> dict:
    field = f"{side}.firewall_group_ids"
    if not isinstance(ids, list) or not ids:
        return validation_error(f"{field} must be a non-empty list of firewall group ids.")
    error = _first_error(*(check_id(i, field) for i in ids))
    return error or {"filter_type": "FIREWALL_GROUPS", "firewall_group_ids": list(ids)}


def _address_port_filter(side: str, spec: dict, ip_version: str) -> dict:
    out: dict = {"filter_type": "ADDRESS_AND_PORT"}
    for key, value_key in (("invert_address", "address"), ("invert_port", "port")):
        flag = spec.get(key, False)
        error = _check_bool(flag, f"{side}.{key}")
        if error:
            return error
        if flag and value_key not in spec:
            return validation_error(f"{side}.{key} needs {side}.{value_key}.")
    if "address" in spec:
        address = address_value(spec["address"], f"{side}.address", ip_version, allow_cidr=True)
        if is_error(address):
            return address
        out["address"] = address
    if "port" in spec:
        port = port_value(spec["port"], f"{side}.port", allow_range=True)
        if is_error(port):
            return port
        out["port"] = port
    if "address" not in out and "port" not in out:
        return dict(_NONE_FILTER)
    out["invert_address"] = spec.get("invert_address", False)
    out["invert_port"] = spec.get("invert_port", False)
    return out


def filter_ports(body: dict) -> bool:
    """Whether the rule matches or translates a port (which needs a tcp/udp protocol)."""
    return "port" in body or any(
        "port" in (body.get(key) or {}) for key in ("source_filter", "destination_filter")
    )


# --- rules ------------------------------------------------------------------

def _check_scalars(args: dict) -> dict | None:
    return _first_error(
        _check_description(args["description"]),
        check_enum(args["nat_type"], NAT_TYPES, "nat_type"),
        check_enum(args["protocol"], PROTOCOLS, "protocol"),
        check_enum(args["ip_version"], IP_VERSIONS, "ip_version"),
        *(_check_bool(args[f], f) for f in ("exclude", "enabled", "logging")),
        _check_rule_index(args["rule_index"]),
    )


def _check_interfaces(nat_type: str, in_interface: Any, out_interface: Any) -> dict | None:
    wanted, unwanted = ("in_interface", "out_interface") if nat_type == "DNAT" else ("out_interface", "in_interface")
    values = {"in_interface": in_interface, "out_interface": out_interface}
    if values[wanted] is None:
        return validation_error(f"{nat_type} rules need {wanted} (a network id from list_networks).")
    if values[unwanted] is not None:
        return validation_error(f"{nat_type} rules take {wanted}, not {unwanted}.")
    return check_id(values[wanted], wanted)


def _check_translation(args: dict) -> dict | None:
    nat_type, exclude = args["nat_type"], args["exclude"]
    ip, port = args["translated_ip"], args["translated_port"]
    if nat_type == "MASQUERADE":
        for field, value in (("translated_ip", ip), ("translated_port", port)):
            if value is not None:
                return validation_error(f"MASQUERADE rules use the outgoing interface's address; omit {field}.")
        return None
    if exclude:
        for field, value in (("translated_ip", ip), ("translated_port", port)):
            if value is not None:
                return validation_error(f"An exclude rule skips translation; omit {field}.")
        return None
    if ip is None:
        return validation_error(f"{nat_type} rules need translated_ip (or exclude=True).")
    return None


def _translation_fields(args: dict) -> dict:
    out: dict = {}
    if args["translated_ip"] is not None:
        ip = address_value(args["translated_ip"], "translated_ip", args["ip_version"], allow_cidr=False)
        if is_error(ip):
            return ip
        out["ip_address"] = ip
    if args["translated_port"] is not None:
        port = port_value(args["translated_port"], "translated_port", allow_range=False)
        if is_error(port):
            return port
        out["port"] = port
    return out


def build_rule(*, description, nat_type, protocol, ip_version, in_interface, out_interface,
               translated_ip, translated_port, source, destination, exclude, enabled,
               logging, rule_index) -> dict:
    """Validate tool arguments and build the NAT rule body, or return a VALIDATION_ERROR dict."""
    args = locals()
    error = _first_error(
        _check_scalars(args),
        _check_interfaces(nat_type, in_interface, out_interface),
        _check_translation(args),
    )
    if error:
        return error
    translation = _translation_fields(args)
    source_filter = build_filter("source", source, ip_version)
    destination_filter = build_filter("destination", destination, ip_version)
    error = _first_error(translation, source_filter, destination_filter)
    if error:
        return error
    body: dict = {
        "description": description, "type": nat_type, "protocol": protocol,
        "ip_version": ip_version, "enabled": enabled, "exclude": exclude, "logging": logging,
    }
    if rule_index is not None:
        body["rule_index"] = rule_index
    interface_key = "in_interface" if nat_type == "DNAT" else "out_interface"
    body[interface_key] = in_interface if nat_type == "DNAT" else out_interface
    body.update(translation)
    body["source_filter"] = source_filter
    body["destination_filter"] = destination_filter
    if protocol == "all" and filter_ports(body):
        return validation_error("Matching or translating a port needs protocol tcp, udp or tcp_udp, not 'all'.")
    return body


# --- stored rule back to arguments --------------------------------------------

def _present(value: Any) -> Any:
    """The controller stores absent text fields as ''; treat those as None."""
    return None if value in ("", None) else value


def _filter_to_spec(side: str, stored: Any) -> dict | None:
    if not isinstance(stored, dict):
        return None
    filter_type = stored.get("filter_type", "NONE")
    if filter_type == "NONE":
        return None
    if filter_type == "NETWORK_CONF":
        return {"network_id": stored.get("network_conf_id")}
    if filter_type == "FIREWALL_GROUPS":
        return {"firewall_group_ids": list(stored.get("firewall_group_ids") or [])}
    if filter_type != "ADDRESS_AND_PORT":
        return validation_error(
            f"This rule's {side} filter uses filter_type {clean_text(filter_type, 40)!r}, which these tools do not edit. "
            "Change it in the UniFi UI."
        )
    spec = {key: stored[key] for key in ("address", "port") if _present(stored.get(key)) is not None}
    for flag in ("invert_address", "invert_port"):
        if stored.get(flag) is True:
            spec[flag] = True
    return spec or None


def rule_to_args(rule: dict) -> dict:
    """Keyword arguments for build_rule that rebuild a stored rule, or a VALIDATION_ERROR dict."""
    source = _filter_to_spec("source", rule.get("source_filter"))
    destination = _filter_to_spec("destination", rule.get("destination_filter"))
    error = _first_error(source, destination)
    if error:
        return error
    nat_type = rule.get("type")
    exclude = rule.get("exclude", False)
    return {
        "description": rule.get("description"),
        "nat_type": nat_type,
        "protocol": rule.get("protocol", "all"),
        "ip_version": rule.get("ip_version", "IPV4"),
        "in_interface": _present(rule.get("in_interface")) if nat_type == "DNAT" else None,
        "out_interface": _present(rule.get("out_interface")) if nat_type != "DNAT" else None,
        # An exclude rule never translates; ignore any address or port left on it.
        "translated_ip": None if exclude is True else _present(rule.get("ip_address")),
        "translated_port": None if exclude is True else _present(rule.get("port")),
        "source": source,
        "destination": destination,
        "exclude": exclude,
        "enabled": rule.get("enabled", True),
        "logging": rule.get("logging", False),
        "rule_index": rule.get("rule_index"),
    }
