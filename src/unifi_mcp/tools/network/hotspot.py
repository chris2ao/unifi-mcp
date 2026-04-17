"""Hotspot and voucher tools: list vouchers, create voucher.

Uses V1 stat and cmd API per the endpoint catalog.
"""

from unifi_mcp.auth.client import UnifiClient


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


TOOLS = [list_vouchers, create_voucher]
