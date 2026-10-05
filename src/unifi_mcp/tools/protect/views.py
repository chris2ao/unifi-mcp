"""UniFi Protect live view and viewer tools (Tier 1).

Uses the Integration API at /proxy/protect/integration/v1/ (spec 7.3.70).
list_liveviews lives in cameras.py; this module adds get/create/update for
live views and list/get/assign for Protect viewers (wall displays).
"""

import re

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError

GROUP = "cameras"

TIER2_TOOLS: dict[str, str] = {}

_BASE = "/proxy/protect/integration/v1"
_LIVEVIEW_CACHE = "protect_liveviews"
_VIEWER_CACHE = "protect_viewers"
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_CYCLE_MODES = ("motion", "time")
_UPDATABLE = {"name", "isDefault", "isGlobal", "layout", "slots"}
_ALIASES = {"is_default": "isDefault", "is_global": "isGlobal"}


def _error(message: str) -> dict:
    return {"error": True, "category": "VALIDATION_ERROR", "message": message}


def _not_found(kind: str, item_id: str) -> dict:
    return {
        "error": True, "category": "NOT_FOUND",
        "message": f"No {kind} found with id '{item_id}'", f"{kind}_id": item_id,
    }


def _check_id(value, label: str) -> dict | None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        return _error(
            f"Invalid {label}: must be 1-64 characters of letters, digits, '-' or '_'.",
        )
    return None


def _as_list(response) -> list[dict]:
    if isinstance(response, list):
        return [r for r in response if isinstance(r, dict)]
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []


def _unwrap(response) -> dict:
    if isinstance(response, dict) and isinstance(response.get("data"), dict):
        return response["data"]
    return response if isinstance(response, dict) else {}


def _format_liveview(lv: dict) -> dict:
    return {
        "id": lv.get("id"),
        "name": lv.get("name"),
        "is_default": lv.get("isDefault", False),
        "is_global": lv.get("isGlobal", False),
        "owner": lv.get("owner"),
        "layout": lv.get("layout"),
        "slots": [
            {
                "cameras": s.get("cameras", []),
                "cycle_mode": s.get("cycleMode"),
                "cycle_interval": s.get("cycleInterval"),
            }
            for s in lv.get("slots", []) if isinstance(s, dict)
        ],
    }


def _format_viewer(v: dict) -> dict:
    return {
        "id": v.get("id"),
        "name": v.get("name"),
        "state": v.get("state"),
        "type": v.get("type"),
        "mac": v.get("mac"),
        "liveview_id": v.get("liveview"),
        "stream_limit": v.get("streamLimit"),
    }


def _normalize_slot(slot) -> tuple[dict | None, str | None]:
    """Validate one slot, returning (camelCase slot, error message)."""
    if not isinstance(slot, dict):
        return None, "each slot must be an object."
    cameras = slot.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        return None, "each slot needs a non-empty 'cameras' list of camera IDs."
    for cam in cameras:
        if _check_id(cam, "camera ID"):
            return None, f"invalid camera ID in slot: {cam!r}."
    mode = slot.get("cycleMode", slot.get("cycle_mode", "time"))
    if mode not in _CYCLE_MODES:
        return None, f"cycleMode must be one of {list(_CYCLE_MODES)}."
    interval = slot.get("cycleInterval", slot.get("cycle_interval", 10))
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        return None, "cycleInterval must be a positive number of seconds."
    return {"cameras": list(cameras), "cycleMode": mode, "cycleInterval": interval}, None


def _normalize_slots(slots) -> tuple[list | None, str | None]:
    if not isinstance(slots, list) or not slots:
        return None, "slots must be a non-empty list."
    out = []
    for slot in slots:
        norm, err = _normalize_slot(slot)
        if err:
            return None, err
        out.append(norm)
    return out, None


def _validate_liveview_fields(fields: dict) -> tuple[dict | None, dict | None]:
    """Validate camelCase liveview fields. Returns (clean body, error)."""
    body = dict(fields)
    if "name" in body and (not isinstance(body["name"], str) or not body["name"].strip()):
        return None, _error("name must be a non-empty string.")
    for flag in ("isDefault", "isGlobal"):
        if flag in body and not isinstance(body[flag], bool):
            return None, _error(f"{flag} must be a boolean.")
    if "layout" in body:
        layout = body["layout"]
        if isinstance(layout, bool) or not isinstance(layout, int) or not 1 <= layout <= 26:
            return None, _error("layout must be an integer from 1 to 26 (the slot count).")
    if "slots" in body:
        slots, err = _normalize_slots(body["slots"])
        if err:
            return None, _error(f"Invalid slots: {err}")
        body = {**body, "slots": slots}
    if "layout" in body and "slots" in body and body["layout"] != len(body["slots"]):
        return None, _error(
            f"layout ({body['layout']}) must equal the number of slots ({len(body['slots'])}).",
        )
    return body, None


async def get_liveview(client: UnifiClient, liveview_id: str) -> dict:
    """Get one Protect live view by ID, including each slot's cameras and cycle settings."""
    if (bad := _check_id(liveview_id, "liveview_id")):
        return bad
    try:
        response = await client.get(
            f"{_BASE}/liveviews/{liveview_id}",
            cache_category=_LIVEVIEW_CACHE, cache_ttl=60.0,
        )
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return _not_found("liveview", liveview_id)
        raise
    lv = _unwrap(response)
    if not lv:
        return _not_found("liveview", liveview_id)
    return _format_liveview(lv)


async def create_liveview(
    client: UnifiClient,
    name: str,
    layout: int,
    slots: list[dict],
    is_global: bool = False,
) -> dict:
    """Create a Protect live view. layout is the slot count (1-26) and must equal len(slots).

    Each slot is {"cameras": [camera IDs], "cycleMode": "time"|"motion"
    (default time), "cycleInterval": seconds (default 10)}.
    """
    body, err = _validate_liveview_fields(
        {"name": name, "layout": layout, "slots": slots, "isGlobal": is_global},
    )
    if err:
        return err
    response = await client.post(f"{_BASE}/liveviews", json=body)
    client.invalidate_cache(_LIVEVIEW_CACHE)
    lv = _unwrap(response)
    if not lv:
        return {
            "executed": False, "action": "create_liveview", "liveview": body,
            "message": "The console returned an empty response; the live view may not have been created.",
        }
    return {"executed": True, "action": "create_liveview", "liveview": _format_liveview(lv)}


async def update_liveview(client: UnifiClient, liveview_id: str, updates: dict) -> dict:
    """Update a live view. updates may contain name, isDefault, isGlobal, layout, slots (layout must equal slot count).

    Changing slots alone sets layout to the new slot count automatically; layout
    alone is rejected.
    """
    if (bad := _check_id(liveview_id, "liveview_id")):
        return bad
    if not isinstance(updates, dict) or not updates:
        return _error("updates must be a non-empty dict.")
    renamed = {_ALIASES.get(k, k): v for k, v in updates.items()}
    unknown = sorted(set(renamed) - _UPDATABLE)
    if unknown:
        return _error(f"Unsupported fields: {unknown}. Allowed: {sorted(_UPDATABLE)}.")
    body, err = _validate_liveview_fields(renamed)
    if err:
        return err
    if "layout" in body and "slots" not in body:
        return _error(
            "layout is the slot count: pass slots together with layout, or change "
            "slots alone and layout is set to match.",
        )
    if "slots" in body and "layout" not in body:
        body = {**body, "layout": len(body["slots"])}
    try:
        response = await client.patch(f"{_BASE}/liveviews/{liveview_id}", json=body)
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return _not_found("liveview", liveview_id)
        raise
    client.invalidate_cache(_LIVEVIEW_CACHE)
    lv = _unwrap(response)
    if not lv:
        return {
            "executed": False, "action": "update_liveview", "liveview_id": liveview_id,
            "message": "The console returned an empty response; the change may not have applied.",
        }
    return {"executed": True, "action": "update_liveview", "liveview": _format_liveview(lv)}


async def list_viewers(client: UnifiClient) -> list[dict]:
    """List Protect viewers (wall display devices) with state and assigned live view ID."""
    response = await client.get(
        f"{_BASE}/viewers", cache_category=_VIEWER_CACHE, cache_ttl=30.0,
    )
    return [_format_viewer(v) for v in _as_list(response)]


async def get_viewer(client: UnifiClient, viewer_id: str) -> dict:
    """Get one Protect viewer by ID (state, MAC, stream limit, assigned live view)."""
    if (bad := _check_id(viewer_id, "viewer_id")):
        return bad
    try:
        response = await client.get(
            f"{_BASE}/viewers/{viewer_id}",
            cache_category=_VIEWER_CACHE, cache_ttl=30.0,
        )
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return _not_found("viewer", viewer_id)
        raise
    viewer = _unwrap(response)
    if not viewer:
        return _not_found("viewer", viewer_id)
    return _format_viewer(viewer)


async def set_viewer_liveview(
    client: UnifiClient, viewer_id: str, liveview_id: str | None,
) -> dict:
    """Assign a live view to a Protect viewer (wall display). Pass liveview_id=None to clear the assignment."""
    if (bad := _check_id(viewer_id, "viewer_id")):
        return bad
    if liveview_id is not None and (bad := _check_id(liveview_id, "liveview_id")):
        return bad
    try:
        response = await client.patch(
            f"{_BASE}/viewers/{viewer_id}", json={"liveview": liveview_id},
        )
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return _not_found("viewer", viewer_id)
        raise
    client.invalidate_cache(_VIEWER_CACHE)
    viewer = _unwrap(response)
    if not viewer:
        return {
            "executed": False, "action": "set_viewer_liveview", "viewer_id": viewer_id,
            "message": "The console returned an empty response; the assignment may not have applied.",
        }
    return {"executed": True, "action": "set_viewer_liveview", "viewer": _format_viewer(viewer)}


TOOLS = [
    get_liveview,
    create_liveview,
    update_liveview,
    list_viewers,
    get_viewer,
    set_viewer_liveview,
]
