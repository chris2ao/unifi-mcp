"""UniFi Protect live event and device-update streaming.

The Protect Integration API (spec 7.3.70) exposes events only over WebSocket:
GET /v1/subscribe/events (events) and /v1/subscribe/devices (device changes).
There is no REST event history, so every tool here captures a LIVE window: it
connects, collects messages for a bounded number of seconds, then closes.
Events that happened before the call are never returned.
"""

import asyncio
import json
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import websockets

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError
from unifi_mcp.validation import check_id, validation_error

GROUP = "cameras"

TIER2_TOOLS: dict[str, str] = {}

_BASE = "/proxy/protect/integration/v1"
MAX_SECONDS = 120
MAX_EVENTS = 500
_SMART_TYPES = ("smartDetectZone", "smartDetectLine", "smartDetectLoiterZone", "smartAudioDetect")


def _ws_url(host: str, channel: str) -> str:
    parts = urlsplit(host if "://" in host else f"https://{host}")
    scheme = "ws" if parts.scheme == "http" else "wss"
    return f"{scheme}://{parts.netloc}{_BASE}/subscribe/{channel}"


def _ssl_context(url: str, verify: bool):
    if not url.startswith("wss://"):
        return None
    if verify:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _iso(ms) -> str | None:
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _clamp(value, ceiling: int, label: str):
    """Return (clamped_value, error). Accepts positive numbers only."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None, validation_error(f"{label} must be a positive number.")
    return min(value, ceiling), None


def _parse_json(raw) -> dict | None:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def _stream(client: UnifiClient, channel: str, seconds: float, limit: int, accept):
    """Collect up to `limit` accepted messages within `seconds`, then close.

    `accept(parsed_message)` returns a compact dict, or None to drop the message.
    Returns (collected, total_messages_seen).
    """
    url = _ws_url(client.config.unifi_host, channel)
    ctx = _ssl_context(url, client.config.unifi_verify_ssl)
    kwargs = {"additional_headers": {"X-API-Key": client.config.unifi_api_key}, "open_timeout": 10}
    if ctx is not None:
        kwargs["ssl"] = ctx
    collected: list[dict] = []
    seen = 0
    deadline = time.monotonic() + seconds
    async with websockets.connect(url, **kwargs) as ws:
        while len(collected) < limit:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), remaining)
            except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                break
            seen += 1
            parsed = _parse_json(raw)
            compact = accept(parsed) if parsed else None
            if compact is not None:
                collected = [*collected, compact]
    return collected, seen


def _compact_event(msg: dict, names: dict) -> dict | None:
    item = msg.get("item")
    if not isinstance(item, dict):
        return None
    device = item.get("device")
    return {
        "message_type": msg.get("type"),
        "event_id": item.get("id"),
        "event_type": item.get("type"),
        "camera_id": device,
        "camera_name": names.get(device),
        "smart_detect_types": item.get("smartDetectTypes") or [],
        "score": item.get("score"),
        "start": _iso(item.get("start")),
        "end": _iso(item.get("end")),
    }


async def _camera_names(client: UnifiClient) -> tuple[dict, str | None]:
    try:
        cams = await client.get_all_pages(
            f"{_BASE}/cameras", cache_category="protect_cameras", cache_ttl=60.0,
        )
    except UnifiError as e:
        return {}, f"Camera names unavailable: {e}"
    return {c.get("id"): c.get("name") for c in cams if isinstance(c, dict)}, None


def _event_filter(event_types, detect_types, camera_id, names):
    wanted = set(event_types or [])
    detects = set(detect_types or [])

    def accept(msg: dict) -> dict | None:
        compact = _compact_event(msg, names)
        if compact is None:
            return None
        if wanted and compact["event_type"] not in wanted:
            return None
        if camera_id and compact["camera_id"] != camera_id:
            return None
        if detects and not detects.intersection(compact["smart_detect_types"]):
            return None
        return compact

    return accept


def _check_filters(event_types, detect_types, camera_id) -> dict | None:
    for label, value in (("event_types", event_types), ("detect_types", detect_types)):
        if value is not None and (
            not isinstance(value, list) or not all(isinstance(v, str) and v for v in value)
        ):
            return validation_error(f"{label} must be a list of non-empty strings.")
    if camera_id is not None:
        return check_id(camera_id, "camera_id")
    return None


def _merge_events(messages: list[dict]) -> list[dict]:
    """Collapse add/update messages for one event id into a single event.

    The latest message wins field by field, but a missing (None or empty) value
    never overwrites one already seen, so `start` from the add and `end` from
    the update are both kept. Messages without an id stay separate.
    """
    merged: dict = {}
    for i, msg in enumerate(messages):
        key = msg.get("event_id") or ("anon", i)
        prior = merged.get(key)
        if prior is None:
            merged = {**merged, key: msg}
            continue
        updated = {
            k: (v if v not in (None, [], "") else prior.get(k)) for k, v in msg.items()
        }
        merged = {**merged, key: updated}
    return list(merged.values())


async def _watch(
    client, seconds, max_events, event_types, detect_types, camera_id, tool,
) -> dict:
    err = _check_filters(event_types, detect_types, camera_id)
    secs, e1 = _clamp(seconds, MAX_SECONDS, "seconds")
    cap, e2 = _clamp(max_events, MAX_EVENTS, "max_events")
    err = err or e1 or e2
    if err:
        return err
    names, note = await _camera_names(client)
    accept = _event_filter(event_types, detect_types, camera_id, names)
    try:
        events, seen = await _stream(client, "events", secs, int(cap), accept)
    except (OSError, websockets.exceptions.WebSocketException) as e:
        return {
            "error": True, "category": "CONNECTION_ERROR", "tool": tool,
            "message": f"Could not read the Protect events WebSocket: {type(e).__name__}: {e}",
        }
    events = _merge_events(events)
    result = {
        "tool": tool, "window_seconds": secs, "messages_seen": seen,
        "count": len(events), "events": events,
        "note": (
            "Live capture window only. Protect has no REST event history. "
            "count is distinct events (add and update messages for one event id "
            "are merged); messages_seen is the raw WebSocket message volume."
        ),
    }
    if seconds > MAX_SECONDS or max_events > MAX_EVENTS:
        result["capped"] = True
    return {**result, "warning": note} if note else result


async def watch_protect_events(
    client: UnifiClient, seconds: int = 30, event_types: list[str] | None = None,
    camera_id: str | None = None, max_events: int = 100,
) -> dict:
    """Listen to the live Protect event stream for a short window and return what arrives.

    Connects to the Protect events WebSocket for `seconds` (default 30, hard cap
    120), then closes. event_types filters by event type (for example motion,
    smartDetectZone, smartDetectLine, ring, sensorMotion); omit for all.
    camera_id limits to one camera/device id. max_events caps results (default
    100, hard cap 500). Returns compact events with type, camera id and name,
    smart detect types, score, and ISO start/end. Only events occurring during
    the window are seen; there is no history.
    """
    return await _watch(
        client, seconds, max_events, event_types, None, camera_id, "watch_protect_events",
    )


async def list_motion_events(
    client: UnifiClient, seconds: int = 30, camera_id: str | None = None,
) -> dict:
    """Capture camera motion events during a LIVE window of `seconds` (default 30, max 120).

    Protect has no REST event history: this listens on the live WebSocket and
    returns only motion events that start or end while it is listening. An empty
    result means no motion occurred during the window, not that none happened
    earlier. camera_id limits to one camera.
    """
    return await _watch(
        client, seconds, 100, ["motion"], None, camera_id, "list_motion_events",
    )


async def list_smart_detections(
    client: UnifiClient, seconds: int = 30, detect_types: list[str] | None = None,
    camera_id: str | None = None,
) -> dict:
    """Capture smart detections (person, vehicle, animal, package...) during a LIVE window.

    Protect has no REST event history: this listens on the live WebSocket for
    `seconds` (default 30, max 120) and returns only detections that occur during
    that window. detect_types filters smart detect types such as person, vehicle,
    package, licensePlate, face, animal. camera_id limits to one camera.
    """
    return await _watch(
        client, seconds, 100, list(_SMART_TYPES), detect_types, camera_id,
        "list_smart_detections",
    )


def _device_ids(item: dict) -> list:
    raw = item.get("id")
    return list(raw) if isinstance(raw, list) else [raw]


def _compact_device(msg: dict) -> dict | None:
    item = msg.get("item")
    if not isinstance(item, dict):
        return None
    changed = sorted(k for k in item if k not in ("id", "modelKey"))
    return {
        "message_type": msg.get("type"),
        "model_key": item.get("modelKey"),
        "device_ids": _device_ids(item),
        "name": item.get("name"),
        "state": item.get("state"),
        "changed_fields": changed,
    }


async def watch_protect_device_updates(
    client: UnifiClient, seconds: int = 15, max_messages: int = 100,
) -> dict:
    """Listen to live Protect device changes (add, update, remove) for a short window.

    Connects to the Protect devices WebSocket for `seconds` (default 15, hard cap
    120), then closes. max_messages caps results (default 100, hard cap 500).
    Each message gives the change type, device model key and ids, name, state,
    and which fields changed. Live window only; no history.
    """
    secs, e1 = _clamp(seconds, MAX_SECONDS, "seconds")
    cap, e2 = _clamp(max_messages, MAX_EVENTS, "max_messages")
    if e1 or e2:
        return e1 or e2
    try:
        msgs, seen = await _stream(client, "devices", secs, int(cap), _compact_device)
    except (OSError, websockets.exceptions.WebSocketException) as e:
        return {
            "error": True, "category": "CONNECTION_ERROR", "tool": "watch_protect_device_updates",
            "message": f"Could not read the Protect devices WebSocket: {type(e).__name__}: {e}",
        }
    return {
        "tool": "watch_protect_device_updates", "window_seconds": secs,
        "messages_seen": seen, "count": len(msgs), "messages": msgs,
        "note": "Live capture window only. Protect has no REST device-change history.",
    }


TOOLS = [
    watch_protect_events, list_motion_events, list_smart_detections,
    watch_protect_device_updates,
]
