"""Body builders for official-API zone-based firewall policies.

Pure functions that turn simple tool arguments (IP strings, port numbers,
network ids, protocol names) into the Integration API policy shapes. Every
builder returns either the built value or a VALIDATION_ERROR dict, so callers
can fail fast before any request is sent.

Shapes follow the 10.6.106 spec ("Create or update firewall policy") and were
checked against policies read live from the console on 2026-10-26.
"""

import ipaddress
import re

from unifi_mcp.validation import validation_error

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
ACTIONS = ("ALLOW", "BLOCK", "REJECT")
CONNECTION_STATES = ("NEW", "INVALID", "ESTABLISHED", "RELATED")
IP_VERSIONS = ("IPV4", "IPV4_AND_IPV6", "IPV6")
# Protocols that can carry port matching.
_PORT_PROTOCOLS = ("tcp", "udp", "tcp_udp")
# Upper-case names match what the console returns ({"name": "TCP"} on 10.6.106).
_NAMED_PROTOCOLS = {"tcp": "TCP", "udp": "UDP", "icmp": "ICMP"}
_PORT_PROTOCOL_NUMBERS = (6, 17)  # TCP, UDP
# trafficFilter keys that hold the IP or network matcher, by filter type.
MATCHER_KEYS = {"IP_ADDRESS": "ipAddressFilter", "NETWORK": "networkFilter"}
PROTOCOLS = ("all", "tcp_udp", *_NAMED_PROTOCOLS)


def is_error(value) -> bool:
    return isinstance(value, dict) and value.get("error") is True


def check_uuid(value, field: str) -> dict | None:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        return validation_error(f"{field} must be an Integration API UUID. Got: {value!r}.")
    return None


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(text.strip())


def ip_item(value) -> dict:
    """One address, CIDR subnet or 'start-stop' range as an IP matching item."""
    if not isinstance(value, str) or not value.strip():
        return validation_error(f"IP entries must be non-empty strings. Got: {value!r}.")
    text = value.strip()
    try:
        if "/" in text:
            net = ipaddress.ip_network(text, strict=True)
            return {"type": "SUBNET", "value": str(net)}
        if "-" in text:
            start_text, stop_text = text.split("-", 1)
            start, stop = _ip(start_text), _ip(stop_text)
            if start.version != stop.version or int(start) > int(stop):
                raise ValueError("range start must not be after stop")
            return {"type": "IP_ADDRESS_RANGE", "start": str(start), "stop": str(stop)}
        return {"type": "IP_ADDRESS", "value": str(_ip(text))}
    except ValueError as e:
        return validation_error(
            f"Invalid IP entry {value!r} ({e}). Use an address, a subnet with no host "
            "bits set (192.0.2.0/24), or a range (192.0.2.10-192.0.2.20)."
        )


def _port_number(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    return number if 1 <= number <= 65535 else None


def port_item(value) -> dict:
    """One port (53 or '53') or 'start-stop' range as a port matching item."""
    if isinstance(value, str) and "-" in value:
        start_text, stop_text = value.split("-", 1)
        start, stop = _port_number(start_text), _port_number(stop_text)
        if start is not None and stop is not None and start <= stop:
            return {"type": "PORT_NUMBER_RANGE", "start": start, "stop": stop}
    else:
        number = _port_number(value)
        if number is not None:
            return {"type": "PORT_NUMBER", "value": number}
    return validation_error(
        f"Invalid port {value!r}. Use a number from 1 to 65535 or a range like '8000-8100'."
    )


def _has_duplicates(items: list) -> bool:
    keys = [repr(sorted(i.items())) if isinstance(i, dict) else repr(i) for i in items]
    return len(set(keys)) != len(keys)


def _items(values, field: str, convert) -> list | dict:
    if not isinstance(values, list) or not values:
        return validation_error(f"{field} must be a non-empty list (omit it to match any).")
    items = [convert(v) for v in values]
    if err := next((i for i in items if is_error(i)), None):
        return err
    if _has_duplicates(items):
        return validation_error(f"{field} contains duplicate entries: {values!r}.")
    return items


def _port_filter(items: list) -> dict:
    return {"type": "PORTS", "matchOpposite": False, "items": items}


def build_endpoint(
    zone_id: str,
    *,
    side: str,
    ips: list | None = None,
    network_ids: list | None = None,
    ports: list | None = None,
) -> dict:
    """Build a policy source or destination: a zone plus optional IP or network and port filters."""
    if err := check_uuid(zone_id, f"{side}_zone_id"):
        return err
    if ips is not None and network_ids is not None:
        return validation_error(f"Use {side}_ips or {side}_network_ids, not both.")
    port_items = _items(ports, f"{side}_ports", port_item) if ports is not None else None
    if is_error(port_items):
        return port_items
    traffic: dict | None = None
    if ips is not None:
        ip_items = _items(ips, f"{side}_ips", ip_item)
        if is_error(ip_items):
            return ip_items
        traffic = {
            "type": "IP_ADDRESS",
            "ipAddressFilter": {"type": "IP_ADDRESSES", "matchOpposite": False, "items": ip_items},
        }
    elif network_ids is not None:
        if not isinstance(network_ids, list) or not network_ids:
            return validation_error(f"{side}_network_ids must be a non-empty list.")
        for network_id in network_ids:
            if err := check_uuid(network_id, f"{side}_network_ids"):
                return err
        if _has_duplicates(network_ids):
            return validation_error(f"{side}_network_ids contains duplicate entries.")
        traffic = {"type": "NETWORK", "networkFilter": {"networkIds": list(network_ids), "matchOpposite": False}}
    port_filter = _port_filter(port_items) if port_items is not None else None
    return join_endpoint(zone_id, traffic, port_filter)


def join_endpoint(zone_id: str, matcher: dict | None, port_filter: dict | None) -> dict:
    """Combine an IP or network matcher and a port filter into a source or destination."""
    traffic = matcher
    if port_filter:
        traffic = (matcher or {"type": "PORT"}) | {"portFilter": port_filter}
    return {"zoneId": zone_id} | ({"trafficFilter": traffic} if traffic else {})


def matcher_part(traffic_filter: dict) -> dict | None:
    """The IP or network matcher of a trafficFilter (type plus its filter), if any."""
    key = MATCHER_KEYS.get((traffic_filter or {}).get("type"))
    return {"type": traffic_filter["type"], key: traffic_filter[key]} if key and key in traffic_filter else None


def mergeable(traffic_filter: dict) -> bool:
    """True when a trafficFilter only uses parts these tools can rebuild."""
    if not traffic_filter:
        return True
    kind = traffic_filter.get("type")
    allowed = {"type", "portFilter", *([MATCHER_KEYS[kind]] if kind in MATCHER_KEYS else [])}
    return kind in (*MATCHER_KEYS, "PORT") and set(traffic_filter) <= allowed


def check_ip_family(endpoint: dict, ip_version: str) -> dict | None:
    """Reject IP entries of the other family on an IPv4-only or IPv6-only rule."""
    want = {"IPV4": 4, "IPV6": 6}.get(ip_version)
    ip_filter = ((endpoint or {}).get("trafficFilter") or {}).get("ipAddressFilter") or {}
    if want is None:
        return None
    for item in ip_filter.get("items") or []:
        text = item.get("value") or item.get("start", "")
        version = ipaddress.ip_network(text, strict=False).version if text else want
        if version != want:
            return validation_error(f"IP entry {text!r} does not match ip_version {ip_version!r}.")
    return None


def endpoint_has_ports(endpoint: dict) -> bool:
    return "portFilter" in ((endpoint or {}).get("trafficFilter") or {})


def build_ip_scope(protocol: str, ip_version: str, *, has_ports: bool) -> dict:
    """Build ipProtocolScope. 'all' matches every protocol; ports need tcp, udp or tcp_udp."""
    proto = protocol.lower() if isinstance(protocol, str) else protocol
    if proto not in PROTOCOLS:
        return validation_error(f"protocol must be one of {list(PROTOCOLS)}. Got: {protocol!r}.")
    if ip_version not in IP_VERSIONS:
        return validation_error(f"ip_version must be one of {list(IP_VERSIONS)}. Got: {ip_version!r}.")
    if has_ports and proto not in _PORT_PROTOCOLS:
        return validation_error(
            f"Port matching needs protocol tcp, udp or tcp_udp (got {protocol!r})."
        )
    if proto == "icmp" and ip_version != "IPV4":
        return validation_error("protocol 'icmp' needs ip_version 'IPV4'.")
    scope: dict = {"ipVersion": ip_version}
    if proto == "tcp_udp":
        scope["protocolFilter"] = {"type": "PRESET", "preset": {"name": "TCP_UDP"}}
    elif proto in _NAMED_PROTOCOLS:
        scope["protocolFilter"] = {
            "type": "NAMED_PROTOCOL", "protocol": {"name": _NAMED_PROTOCOLS[proto]}, "matchOpposite": False,
        }
    return scope


def scope_allows_ports(scope: dict) -> bool:
    """True when an existing ipProtocolScope matches only TCP and/or UDP."""
    pf = (scope or {}).get("protocolFilter") or {}
    if pf.get("matchOpposite"):
        return False
    if pf.get("type") == "PRESET":
        return str((pf.get("preset") or {}).get("name", "")).upper() == "TCP_UDP"
    if pf.get("type") == "NAMED_PROTOCOL":
        return str((pf.get("protocol") or {}).get("name", "")).upper() in ("TCP", "UDP")
    if pf.get("type") == "PROTOCOL_NUMBER":
        return pf.get("protocolNumber") in _PORT_PROTOCOL_NUMBERS
    return False


def build_action(action: str, *, allow_return_traffic: bool) -> dict:
    name = action.upper() if isinstance(action, str) else action
    if name not in ACTIONS:
        return validation_error(f"action must be one of {list(ACTIONS)}. Got: {action!r}.")
    if not isinstance(allow_return_traffic, bool):
        return validation_error("allow_return_traffic must be a boolean.")
    if allow_return_traffic and name != "ALLOW":
        return validation_error("allow_return_traffic only applies to ALLOW policies.")
    return {"type": "ALLOW", "allowReturnTraffic": allow_return_traffic} if name == "ALLOW" else {"type": name}


def check_connection_states(states) -> list | dict:
    """Validate and upper-case a connection state list (omit the list to match all states)."""
    if not isinstance(states, list) or not states:
        return validation_error(
            f"connection_states must be a non-empty list drawn from {list(CONNECTION_STATES)}."
        )
    upper = [s.upper() if isinstance(s, str) else s for s in states]
    if any(s not in CONNECTION_STATES for s in upper) or len(set(upper)) != len(upper):
        return validation_error(
            f"connection_states must be unique values from {list(CONNECTION_STATES)}. Got: {states!r}."
        )
    return upper
