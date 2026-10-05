"""Hotspot and voucher tools: list/create (legacy API), get/list/delete (official API).

Legacy tools use the V1 stat and cmd API. The v1 tools use the official
Integration API under /proxy/network/integration/v1/sites/{site_id}/hotspot/vouchers.
"""

from urllib.parse import quote

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError
from unifi_mcp.validation import check_id, validation_error

TIER2_TOOLS: dict[str, str] = {
    "delete_voucher": "hotspot",
    "delete_vouchers": "hotspot",
}

_PREVIEW_MAX_ITEMS = 5000
_VOUCHERS = "/proxy/network/integration/v1/sites/{site_id}/hotspot/vouchers"
_PREVIEW_SAMPLE = 20
_MAX_FILTER_LEN = 1000


async def list_vouchers(client: UnifiClient) -> list[dict]:
    """List all guest network vouchers."""
    response = await client.get(
        "/proxy/network/api/s/{site}/stat/voucher",
        cache_category="hotspot", cache_ttl=30.0,
    )
    return [
        {
            "id": v.get("_id", ""),
            "code": v.get("code", ""),
            "quota": v.get("quota", 0),
            "duration": v.get("duration", 0),
            "used": v.get("used", 0),
            "note": v.get("note", ""),
        }
        for v in response["data"]
    ]


async def create_voucher(
    client: UnifiClient,
    expire_minutes: int = 1440,
    quota: int = 1,
    count: int = 1,
    note: str = "",
) -> dict:
    """Create guest network vouchers. Tier 1 (creates access credentials, not destructive)."""
    payload = {
        "cmd": "create-voucher",
        "n": count,
        "expire_number": expire_minutes,
        "expire_unit": 1,  # 1 = minutes
        "usage_quota": quota,
    }
    if note:
        payload["note"] = note

    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/hotspot",
        json=payload,
    )
    return {"action": "create_voucher", "count": count, "response": response}


def _format_voucher(v: dict) -> dict:
    return {
        "id": v.get("id", ""),
        "name": v.get("name", ""),
        "code": v.get("code", ""),
        "created_at": v.get("createdAt"),
        "activated_at": v.get("activatedAt"),
        "expires_at": v.get("expiresAt"),
        "expired": v.get("expired", False),
        "time_limit_minutes": v.get("timeLimitMinutes"),
        "guest_limit": v.get("authorizedGuestLimit"),
        "guest_count": v.get("authorizedGuestCount", 0),
        "data_limit_mb": v.get("dataUsageLimitMBytes"),
        "rx_limit_kbps": v.get("rxRateLimitKbps"),
        "tx_limit_kbps": v.get("txRateLimitKbps"),
    }


def _check_filter(value: object, required: bool) -> dict | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        return validation_error(
            "filter must be a non-empty filter expression such as name.eq('hotel-guest') "
            "or expired.eq(true)."
        )
    if len(value) > _MAX_FILTER_LEN:
        return validation_error(f"filter must be at most {_MAX_FILTER_LEN} characters.")
    return None


async def list_vouchers_v1(client: UnifiClient, filter: str | None = None) -> list[dict] | dict:  # noqa: A002
    """List hotspot vouchers from the official API with limits, usage and expiry, optionally filtered.

    `filter` is an official filter expression, for example name.eq('hotel-guest'),
    expired.eq(true), or and(expired.eq(false), authorizedGuestCount.gt(0)).
    Returns every matching voucher (paginated automatically).
    """
    err = _check_filter(filter, required=False)
    if err:
        return err
    items = await client.get_all_pages(
        _VOUCHERS, filter=filter, cache_category="hotspot", cache_ttl=30.0,
    )
    return [_format_voucher(v) for v in items if isinstance(v, dict)]


async def get_voucher(client: UnifiClient, voucher_id: str) -> dict:
    """Get one hotspot voucher by id (code, limits, guest usage, expiry)."""
    return await _fetch_voucher(client, voucher_id, fresh=False)


async def _fetch_voucher(client: UnifiClient, voucher_id: str, *, fresh: bool) -> dict:
    """Read one voucher; `fresh=True` bypasses the cache (used by delete previews)."""
    cache_args = {} if fresh else {"cache_category": "hotspot", "cache_ttl": 30.0}
    err = check_id(voucher_id, "voucher_id")
    if err:
        return err
    try:
        response = await client.get(f"{_VOUCHERS}/{voucher_id}", **cache_args)
    except UnifiError as e:
        return e.to_dict()
    if isinstance(response, dict) and isinstance(response.get("data"), list):
        response = response["data"][0] if response["data"] else {}
    return _format_voucher(response if isinstance(response, dict) else {})


def _deleted_count(response: object) -> int | None:
    if isinstance(response, dict) and isinstance(response.get("vouchersDeleted"), int):
        return response["vouchersDeleted"]
    return None


def _deletion_result(action: str, response: object, **extra) -> dict:
    count = _deleted_count(response)
    result = {"action": action, **extra, "response": response}
    if count is None or count == 0:
        return {
            **result, "executed": False,
            "message": "The console accepted the request but reported no vouchers deleted. "
                       "Verify with list_vouchers_v1.",
        }
    return {**result, "executed": True, "vouchers_deleted": count}


async def delete_voucher(client: UnifiClient, voucher_id: str, confirm: bool = False) -> dict:
    """Delete one hotspot voucher by id. Guests authorized by it lose access. Requires confirm=True after previewing."""
    err = check_id(voucher_id, "voucher_id")
    if err:
        return err
    if not confirm:
        voucher = await _fetch_voucher(client, voucher_id, fresh=True)
        if voucher.get("error"):
            return voucher
        active = bool(voucher.get("activated_at")) and not voucher.get("expired")
        return {
            "preview": True,
            "action": "delete_voucher",
            "voucher_id": voucher_id,
            "voucher": voucher,
            "impact": (
                "This voucher is active: guests authorized with it will be unauthorized."
                if active else "The voucher is unused or expired; no guest is affected."
            ),
            "message": f"Will delete voucher {voucher_id}. Call again with confirm=True to execute.",
        }
    response = await client.delete(f"{_VOUCHERS}/{voucher_id}")
    client.invalidate_cache("hotspot")
    return _deletion_result("delete_voucher", response, voucher_id=voucher_id)


async def delete_vouchers(client: UnifiClient, filter: str, confirm: bool = False) -> dict:  # noqa: A002
    """Delete every hotspot voucher matching a filter expression, such as expired.eq(true) or name.eq('hotel-guest').

    The preview lists the matching vouchers and their count. A filter is
    required (an empty filter is rejected so this can never delete all
    vouchers by accident). Requires confirm=True after previewing.
    """
    err = _check_filter(filter, required=True)
    if err:
        return err
    if not confirm:
        try:
            matches = await client.get_all_pages(_VOUCHERS, filter=filter, max_items=_PREVIEW_MAX_ITEMS)
        except UnifiError as e:
            return e.to_dict()
        if not matches:
            return {
                "action": "delete_vouchers", "filter": filter, "matched": 0,
                "executed": False, "message": "No vouchers match the filter; nothing to delete.",
            }
        capped = len(matches) >= _PREVIEW_MAX_ITEMS
        shown = [_format_voucher(v) for v in matches[:_PREVIEW_SAMPLE] if isinstance(v, dict)]
        active = sum(1 for v in matches if isinstance(v, dict) and v.get("activatedAt") and not v.get("expired"))
        return {
            "preview": True,
            "action": "delete_vouchers",
            "filter": filter,
            "match_count": len(matches),
            "count_capped": capped,
            "matches": shown,
            "matches_truncated": len(matches) > len(shown),
            "impact": f"{active} matching voucher(s) are active; guests using them will be unauthorized.",
            "message": f"Will delete {'at least ' if capped else ''}{len(matches)} voucher(s) "
                       f"matching {filter}. "
                       + (f"The preview count is capped at {_PREVIEW_MAX_ITEMS}; more may match. "
                          if capped else "")
                       + "Call again with confirm=True to execute.",
        }
    response = await client.delete(f"{_VOUCHERS}?filter={quote(filter, safe='')}")
    client.invalidate_cache("hotspot")
    return _deletion_result("delete_vouchers", response, filter=filter)


TOOLS = [
    list_vouchers, create_voucher, list_vouchers_v1, get_voucher,
    delete_voucher, delete_vouchers,
]
