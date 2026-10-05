"""Traffic Matching List tools: list, get, create, update, delete (Network Integration API).

Endpoints (base /proxy/network/integration/v1/sites/{site_id}):
- GET/POST        /traffic-matching-lists
- GET/PUT/DELETE  /traffic-matching-lists/{trafficMatchingListId}

A traffic matching list is a reusable named set of ports or IP addresses that
firewall policies reference by id (``trafficMatchingListId``). It supersedes
legacy firewall groups. Three list types exist, with these item shapes:

- PORTS:          {"type": "PORT_NUMBER", "value": 1-65535} or
                  {"type": "PORT_NUMBER_RANGE", "start": 1-65535, "stop": 1-65535}
- IPV4_ADDRESSES: IP_ADDRESS (value), SUBNET (value, CIDR),
                  IP_ADDRESS_RANGE (start, stop)
- IPV6_ADDRESSES: IP_ADDRESS (value), SUBNET (value, CIDR)

For convenience, items may also be given as shorthand: ports as 443, "443" or
"8000-8100"; IPs as "192.0.2.5", "198.51.100.0/24" or "10.0.0.10-10.0.0.20".
Lists need at least one item. PUT replaces the whole list.
"""

import ipaddress
from typing import Any

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import ErrorCategory, UnifiError
from unifi_mcp.validation import check_enum, check_id, validation_error

GROUP = "security"
TIER2_TOOLS: dict[str, str] = {
    "create_traffic_matching_list": "zbf",
    "update_traffic_matching_list": "zbf",
    "delete_traffic_matching_list": "zbf",
}

BASE_PATH = "/proxy/network/integration/v1/sites/{site_id}/traffic-matching-lists"
LIST_TYPES = ("PORTS", "IPV4_ADDRESSES", "IPV6_ADDRESSES")
_IP_VERSION = {"IPV4_ADDRESSES": 4, "IPV6_ADDRESSES": 6}
_IP_ITEM_TYPES = {
    "IPV4_ADDRESSES": ("IP_ADDRESS", "SUBNET", "IP_ADDRESS_RANGE"),
    "IPV6_ADDRESSES": ("IP_ADDRESS", "SUBNET"),
}


def _port(value: Any, field: str) -> tuple[int | None, dict | None]:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        return None, validation_error(f"{field} must be an integer port between 1 and 65535. Got: {value!r}.")
    return value, None


def _port_item(item: Any) -> tuple[dict | None, dict | None]:
    if isinstance(item, str) and "-" in item:
        start_s, _, stop_s = item.partition("-")
        item = {"type": "PORT_NUMBER_RANGE", "start": start_s, "stop": stop_s}
    elif not isinstance(item, dict):
        item = {"type": "PORT_NUMBER", "value": item}
    kind = item.get("type")
    err = check_enum(kind, ("PORT_NUMBER", "PORT_NUMBER_RANGE"), "port item type")
    if err:
        return None, err
    if kind == "PORT_NUMBER":
        value, err = _port(item.get("value"), "port value")
        return ({"type": kind, "value": value}, None) if not err else (None, err)
    start, err = _port(item.get("start"), "port range start")
    if err:
        return None, err
    stop, err = _port(item.get("stop"), "port range stop")
    if err:
        return None, err
    if start > stop:
        return None, validation_error(f"Port range start ({start}) must not exceed stop ({stop}).")
    return {"type": kind, "start": start, "stop": stop}, None


def _addr(value: Any, version: int, field: str) -> tuple[str | None, dict | None]:
    try:
        if not isinstance(value, str):
            raise ValueError
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return None, validation_error(f"{field} must be a valid IPv{version} address. Got: {value!r}.")
    if addr.version != version:
        return None, validation_error(f"{field} must be an IPv{version} address. Got: {value!r}.")
    return str(addr) if version == 6 else value.strip(), None


def _subnet(value: Any, version: int) -> tuple[str | None, dict | None]:
    try:
        if not isinstance(value, str) or "/" not in value:
            raise ValueError
        net = ipaddress.ip_network(value.strip(), strict=True)
    except ValueError:
        return None, validation_error(
            f"subnet value must be a valid IPv{version} CIDR with no host bits set "
            f"(for example {'198.51.100.0/24' if version == 4 else '2001:db8:1::/64'}). Got: {value!r}."
        )
    if net.version != version:
        return None, validation_error(f"subnet value must be IPv{version}. Got: {value!r}.")
    return value.strip(), None


def _shorthand_ip_item(item: str) -> dict:
    text = item.strip()
    if "/" in text:
        return {"type": "SUBNET", "value": text}
    if "-" in text:
        start, _, stop = text.partition("-")
        return {"type": "IP_ADDRESS_RANGE", "start": start.strip(), "stop": stop.strip()}
    return {"type": "IP_ADDRESS", "value": text}


def _ip_range(item: dict, version: int) -> tuple[dict | None, dict | None]:
    start, err = _addr(item.get("start"), version, "range start")
    if err:
        return None, err
    stop, err = _addr(item.get("stop"), version, "range stop")
    if err:
        return None, err
    if ipaddress.ip_address(start) > ipaddress.ip_address(stop):
        return None, validation_error(f"Range start ({start}) must not exceed stop ({stop}).")
    return {"type": "IP_ADDRESS_RANGE", "start": start, "stop": stop}, None


def _ip_item(item: Any, list_type: str) -> tuple[dict | None, dict | None]:
    version = _IP_VERSION[list_type]
    if isinstance(item, str):
        item = _shorthand_ip_item(item)
    if not isinstance(item, dict):
        return None, validation_error(f"{list_type} items must be strings or objects. Got: {item!r}.")
    kind = item.get("type")
    err = check_enum(kind, _IP_ITEM_TYPES[list_type], f"{list_type} item type")
    if err:
        return None, err
    if kind == "IP_ADDRESS_RANGE":
        return _ip_range(item, version)
    check = _addr(item.get("value"), version, "ip value") if kind == "IP_ADDRESS" \
        else _subnet(item.get("value"), version)
    value, err = check
    return ({"type": kind, "value": value}, None) if not err else (None, err)


def normalize_items(list_type: str, items: Any) -> tuple[list[dict] | None, dict | None]:
    """Validate items for the list type and return spec-shaped item dicts."""
    if not isinstance(items, (list, tuple)) or not items:
        return None, validation_error("items must be a non-empty list.")
    convert = _port_item if list_type == "PORTS" else (lambda i: _ip_item(i, list_type))
    out: list[dict] = []
    for item in items:
        normalized, err = convert(item)
        if err:
            return None, err
        out.append(normalized)
    return out, None


def _check_name(name: Any) -> dict | None:
    if not isinstance(name, str) or not name.strip():
        return validation_error("name must be a non-empty string.")
    return None


def _unwrap(response: Any) -> dict:
    if isinstance(response, dict) and "data" in response:
        data = response["data"]
        response = data[0] if isinstance(data, list) and data else data
    return response if isinstance(response, dict) else {}


def _page_list(response: Any) -> list:
    if isinstance(response, list):
        return response
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        return response["data"]
    return []


def _format_list(item: dict) -> dict:
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "type": item.get("type", ""),
        "items": item.get("items", []),
    }


def _not_found(list_id: str) -> dict:
    return {
        "error": True, "category": "NOT_FOUND",
        "message": f"No traffic matching list found with id '{list_id}'", "list_id": list_id,
    }


async def _fetch(client: UnifiClient, list_id: str) -> dict | None:
    try:
        response = await client.get(f"{BASE_PATH}/{list_id}")
    except UnifiError as e:
        if e.category == ErrorCategory.NOT_FOUND:
            return None
        raise
    return _unwrap(response) or None


def _executed(action: str, response: Any, **extra: Any) -> dict:
    if not response or response == {"data": []}:
        return {
            "executed": False, "action": action, **extra, "response": response,
            "message": "The console returned an empty response, so the change was probably not applied. "
                       "Re-read the list to verify.",
        }
    return {"executed": True, "action": action, **extra, "response": response}


async def list_traffic_matching_lists(
    client: UnifiClient, type: str | None = None,
) -> list[dict] | dict:
    """List traffic matching lists (reusable port or IP sets referenced by firewall policies).

    Optional ``type`` filters to PORTS, IPV4_ADDRESSES or IPV6_ADDRESSES.
    Each result has id, name, type and items. Follows pagination.
    """
    if type is not None:
        err = check_enum(type, LIST_TYPES, "type")
        if err:
            return err
    lists = await client.get_all_pages(BASE_PATH, cache_category="zbf", cache_ttl=30.0)
    return [
        _format_list(i) for i in lists
        if isinstance(i, dict) and (type is None or i.get("type") == type)
    ]


async def get_traffic_matching_list(client: UnifiClient, list_id: str) -> dict:
    """Get one traffic matching list by UUID, including all its port or IP items."""
    err = check_id(list_id, "list_id")
    if err:
        return err
    found = await _fetch(client, list_id)
    return _format_list(found) if found else _not_found(list_id)


async def create_traffic_matching_list(
    client: UnifiClient, name: str, type: str, items: list, confirm: bool = False,
) -> dict:
    """Create a traffic matching list. Requires confirm=True after previewing.

    ``type`` is PORTS, IPV4_ADDRESSES or IPV6_ADDRESSES. ``items`` is a
    non-empty list. Ports: 443, "8000-8100" (1-65535) or spec objects. IPv4:
    "192.0.2.5", "198.51.100.0/24", "10.0.0.10-10.0.0.20". IPv6: "2001:db8::1",
    "2001:db8:1::/64" (no ranges). Spec objects like {"type": "SUBNET",
    "value": "..."} are also accepted.
    """
    err = _check_name(name) or check_enum(type, LIST_TYPES, "type")
    if err:
        return err
    normalized, err = normalize_items(type, items)
    if err:
        return err
    body = {"type": type, "name": name.strip(), "items": normalized}
    if not confirm:
        return {
            "preview": True, "action": "create_traffic_matching_list", "list": body,
            "message": f"Will create {type} traffic matching list '{body['name']}' with "
                       f"{len(normalized)} item(s). Call again with confirm=True to execute.",
        }
    response = await client.post(BASE_PATH, json=body)
    client.invalidate_cache("zbf")
    return _executed("create_traffic_matching_list", response)


async def update_traffic_matching_list(
    client: UnifiClient, list_id: str, name: str | None = None,
    items: list | None = None, confirm: bool = False,
) -> dict:
    """Update a traffic matching list's name and/or items. Requires confirm=True after previewing.

    Pass ``name``, ``items`` or both. ``items`` REPLACES the whole item set
    (same shorthand as create_traffic_matching_list). The list type cannot be
    changed. The current list is read and the full body is sent, because PUT
    replaces the list.
    """
    err = check_id(list_id, "list_id")
    if err:
        return err
    if name is None and items is None:
        return validation_error("Provide name, items, or both to update.")
    if name is not None:
        err = _check_name(name)
        if err:
            return err
    current = await _fetch(client, list_id)
    if current is None:
        return _not_found(list_id)
    list_type = current.get("type", "")
    new_items = current.get("items", [])
    if items is not None:
        new_items, err = normalize_items(list_type, items)
        if err:
            return err
    body = {
        "type": list_type,
        "name": name.strip() if name is not None else current.get("name", ""),
        "items": new_items,
    }
    if not confirm:
        return {
            "preview": True, "action": "update_traffic_matching_list", "list_id": list_id,
            "current": _format_list(current), "list": body,
            "message": f"Will update traffic matching list {list_id}. "
                       "Call again with confirm=True to execute.",
        }
    response = await client.put(f"{BASE_PATH}/{list_id}", json=body)
    client.invalidate_cache("zbf")
    return _executed("update_traffic_matching_list", response, list_id=list_id)


async def delete_traffic_matching_list(
    client: UnifiClient, list_id: str, confirm: bool = False,
) -> dict:
    """Delete a traffic matching list by UUID. Requires confirm=True after previewing."""
    err = check_id(list_id, "list_id")
    if err:
        return err
    if not confirm:
        current = await _fetch(client, list_id)
        if current is None:
            return _not_found(list_id)
        return {
            "preview": True, "action": "delete_traffic_matching_list", "list_id": list_id,
            "list": _format_list(current),
            "impact": "Firewall policies that reference this list may break or be rejected "
                      "once it is deleted. Use get_zbf_policy on policies that may use this "
                      "list id (trafficMatchingListId) to check first.",
            "message": f"Will delete traffic matching list {list_id}. "
                       "Call again with confirm=True to execute.",
        }
    response = await client.delete(f"{BASE_PATH}/{list_id}")
    client.invalidate_cache("zbf")
    return {"executed": True, "action": "delete_traffic_matching_list", "list_id": list_id, "response": response}


TOOLS = [
    list_traffic_matching_lists,
    get_traffic_matching_list,
    create_traffic_matching_list,
    update_traffic_matching_list,
    delete_traffic_matching_list,
]
