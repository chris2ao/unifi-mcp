"""UniFi Protect camera control tools: PTZ, settings, LED, mic, RTSPS streams.

Uses the Integration API at /proxy/protect/integration/v1/ (spec 7.3.70).
Writes that change camera configuration or stream access are Tier 2
(preview then confirm). PTZ moves and the status LED toggle are Tier 1.
"""

from urllib.parse import urlsplit, urlunsplit

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError
from unifi_mcp.tools.protect.camera_settings_validation import validate_settings
from unifi_mcp.validation import check_enum, check_id, validation_error

GROUP = "cameras"

TIER2_TOOLS = {
    "update_camera_settings": "protect_cameras",
    "disable_camera_mic_permanently": "protect_cameras",
    "create_rtsps_stream": "protect_cameras",
    "delete_rtsps_stream": "protect_cameras",
}

_BASE = "/proxy/protect/integration/v1/cameras"
_CACHE = "protect_cameras"
_PTZ_ACTIONS = ("goto", "patrol_start", "patrol_stop")
_QUALITIES = ("high", "medium", "low", "package")


# --- shared helpers ---

def _unwrap_camera(response) -> dict | None:
    if isinstance(response, list):
        response = response[0] if response else None
    if isinstance(response, dict) and isinstance(response.get("data"), (dict, list)):
        return _unwrap_camera(response["data"])
    if isinstance(response, dict) and response.get("id"):
        return response
    return None


def _not_found(camera_id: str) -> dict:
    return {
        "error": True, "category": "NOT_FOUND",
        "message": f"No camera found with id '{camera_id}'", "camera_id": camera_id,
    }


async def _fetch_camera(client: UnifiClient, camera_id: str) -> tuple[dict | None, dict | None]:
    """Return (camera, error). Exactly one of them is not None."""
    try:
        response = await client.get(
            f"{_BASE}/{camera_id}", cache_category=_CACHE, cache_ttl=15.0,
        )
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return None, _not_found(camera_id)
        raise
    camera = _unwrap_camera(response)
    return (camera, None) if camera else (None, _not_found(camera_id))


def _is_ptz(camera: dict) -> bool | None:
    """True/False from the model name, or None when the type is unknown (attempt the call)."""
    model = camera.get("type")
    if not isinstance(model, str) or not model.strip():
        return None
    return "ptz" in model.lower()


def _is_empty(response) -> bool:
    if response in (None, {}, []):
        return True
    return isinstance(response, dict) and response.get("data") in ([], {}, None) and "data" in response


def _noop(action: str, camera_id: str, **extra) -> dict:
    return {
        "executed": False, "action": action, "camera_id": camera_id, **extra,
        "message": (
            "The console returned HTTP 200 with an empty body, which UniFi uses "
            "for a silent no-op. The change was probably not applied; re-read "
            "the camera to confirm."
        ),
    }


def _executed(client: UnifiClient, action: str, camera_id: str, response, **extra) -> dict:
    client.invalidate_cache(_CACHE)
    return {"executed": True, "action": action, "camera_id": camera_id, **extra, "response": response}


def _mask_url(url):
    """Hide the stream token (the URL path) of an RTSPS URL."""
    if not isinstance(url, str) or not url:
        return url
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/***", parts.query, ""))


def _mask_streams(streams, reveal: bool):
    """Mask stream tokens at any depth (strings, nested dicts and lists)."""
    if reveal:
        return streams
    if isinstance(streams, dict):
        return {k: _mask_streams(v, False) for k, v in streams.items()}
    if isinstance(streams, list):
        return [_mask_streams(v, False) for v in streams]
    if isinstance(streams, str) and streams.lower().startswith("rtsp"):
        return _mask_url(streams)
    return streams


# --- PTZ ---

def _parse_slot(slot, action: str) -> tuple[int | None, dict | None]:
    if action == "patrol_stop":
        return None, None
    if slot is None:
        return None, validation_error(f"slot is required for action '{action}'.")
    text = str(slot)
    if isinstance(slot, bool) or not (text.lstrip("-").isdigit() and text.count("-") <= 1):
        return None, validation_error(f"slot must be an integer. Got: {slot!r}.")
    value = int(text)
    lo, hi = (-1, 99) if action == "goto" else (0, 4)
    if value < lo or value > hi:
        what = "goto slot (-1 is home, 0 and up are presets)" if action == "goto" else "patrol slot (0-4)"
        return None, validation_error(f"{what} must be between {lo} and {hi}. Got: {value}.")
    return value, None


async def ptz_camera(
    client: UnifiClient, camera_id: str, action: str, slot: int | None = None,
) -> dict:
    """Control a PTZ camera. action: 'goto' (move to preset slot, -1 is home), 'patrol_start' (slot 0-4), 'patrol_stop' (no slot).

    Use to point a PTZ camera at a saved preset or start/stop a saved patrol.
    Free pan/tilt/zoom is not offered by the API. Cameras whose model name does
    not contain "PTZ" are refused; when the model is unknown the call is
    attempted and a console rejection is reported as "not PTZ-capable".
    """
    for err in (check_id(camera_id, "camera_id"), check_enum(action, _PTZ_ACTIONS, "action")):
        if err:
            return err
    slot_value, err = _parse_slot(slot, action)
    if err:
        return err
    camera, err = await _fetch_camera(client, camera_id)
    if err:
        return err
    if _is_ptz(camera) is False:
        return {
            "error": True, "category": "VALIDATION_ERROR", "camera_id": camera_id,
            "message": (
                f"Camera '{camera.get('name', camera_id)}' (type {camera.get('type')!r}) "
                "is not PTZ-capable."
            ),
        }
    path = {
        "goto": f"{_BASE}/{camera_id}/ptz/goto/{slot_value}",
        "patrol_start": f"{_BASE}/{camera_id}/ptz/patrol/start/{slot_value}",
        "patrol_stop": f"{_BASE}/{camera_id}/ptz/patrol/stop",
    }[action]
    try:
        response = await client.post(path)
    except UnifiError as e:
        if _is_ptz(camera) is None and e.category == "VALIDATION_ERROR":
            return {
                "error": True, "category": "VALIDATION_ERROR", "camera_id": camera_id,
                "message": (
                    f"The console rejected the PTZ command ({e.message}). The camera "
                    "model is unknown and is probably not PTZ-capable."
                ),
            }
        raise
    client.invalidate_cache(_CACHE)
    return {
        "executed": True, "action": "ptz_camera", "camera_id": camera_id,
        "ptz_action": action, "slot": slot_value, "response": response,
    }


def _diff(settings: dict, camera: dict) -> dict:
    return {
        key: {"current": camera.get(key), "proposed": value}
        for key, value in sorted(settings.items())
    }


async def update_camera_settings(
    client: UnifiClient, camera_id: str, settings: dict, confirm: bool = False,
) -> dict:
    """Change camera settings (Tier 2: preview, then confirm=True). settings keys: osdSettings, ledSettings, lcdMessage, micVolume (1-100), videoMode, hdrType (auto|on|off), smartDetectSettings.

    Pass only the keys to change, for example {"micVolume": 50}. Nested
    objects (osdSettings, ledSettings, smartDetectSettings) are sent as given.
    To rename a camera use update_camera_name. Unknown keys are rejected.
    """
    err = check_id(camera_id, "camera_id")
    if err:
        return err
    if not isinstance(settings, dict) or not settings:
        return validation_error("settings must be a non-empty object.")
    camera, err = await _fetch_camera(client, camera_id)
    if err:
        return err
    err = validate_settings(settings, camera)
    if err:
        return err
    proposed = {k: v for k, v in settings.items()}
    if not confirm:
        return {
            "preview": True, "action": "update_camera_settings", "camera_id": camera_id,
            "camera_name": camera.get("name"), "changes": _diff(proposed, camera),
            "message": "Review the current and proposed values, then call again with confirm=True.",
        }
    response = await client.patch(f"{_BASE}/{camera_id}", json=proposed)
    if _is_empty(response):
        return _noop("update_camera_settings", camera_id, settings=proposed)
    return _executed(client, "update_camera_settings", camera_id, response, settings=proposed)


async def set_camera_led(client: UnifiClient, camera_id: str, enabled: bool) -> dict:
    """Turn a camera's status LED on or off (cosmetic, Tier 1). enabled: true or false."""
    err = check_id(camera_id, "camera_id")
    if err:
        return err
    if not isinstance(enabled, bool):
        return validation_error("enabled must be true or false.")
    response = await client.patch(
        f"{_BASE}/{camera_id}", json={"ledSettings": {"isEnabled": enabled}},
    )
    if _is_empty(response):
        return _noop("set_camera_led", camera_id, enabled=enabled)
    return _executed(client, "set_camera_led", camera_id, response, enabled=enabled)


async def disable_camera_mic_permanently(
    client: UnifiClient, camera_id: str, confirm: bool = False,
) -> dict:
    """PERMANENTLY disable a camera's microphone (Tier 2, IRREVERSIBLE until the camera is factory reset).

    Use only when audio capture must never happen again. Preview first, then
    confirm=True.
    """
    err = check_id(camera_id, "camera_id")
    if err:
        return err
    camera, err = await _fetch_camera(client, camera_id)
    if err:
        return err
    if not confirm:
        return {
            "preview": True, "action": "disable_camera_mic_permanently",
            "camera_id": camera_id, "camera_name": camera.get("name"),
            "impact": (
                "IRREVERSIBLE: the microphone of this camera is disabled "
                "permanently and can only be restored by resetting the camera."
            ),
            "message": "IRREVERSIBLE. Call again with confirm=True to disable the microphone for good.",
        }
    response = await client.post(f"{_BASE}/{camera_id}/disable-mic-permanently")
    if _is_empty(response):
        return _noop("disable_camera_mic_permanently", camera_id)
    return _executed(client, "disable_camera_mic_permanently", camera_id, response)


# --- RTSPS streams ---

def _check_qualities(qualities) -> tuple[list[str], dict | None]:
    if not isinstance(qualities, list) or not qualities:
        return [], validation_error("qualities must be a non-empty list, e.g. ['high', 'medium'].")
    for q in qualities:
        err = check_enum(q, _QUALITIES, "qualities")
        if err:
            return [], err
    return list(dict.fromkeys(qualities)), None


async def _check_package(client, camera_id: str, qualities: list[str]) -> tuple[dict | None, dict | None]:
    camera, err = await _fetch_camera(client, camera_id)
    if err:
        return None, err
    if "package" in qualities and not camera.get("hasPackageCamera"):
        return None, validation_error("The 'package' quality is only available on cameras with a package camera.")
    return camera, None


async def get_rtsps_streams(
    client: UnifiClient, camera_id: str, reveal_urls: bool = False,
) -> dict:
    """List a camera's existing RTSPS stream URLs by quality (high, medium, low, package).

    The secret stream token in each URL is masked unless reveal_urls=True.
    Quality is null when no stream exists; use create_rtsps_stream to add one.
    SECURITY: revealed URLs are bearer credentials. Anyone who can reach the
    console on port 7441 and holds one can watch the camera, and the URL lands
    in the conversation transcript. Reveal only when the user explicitly asks.
    """
    err = check_id(camera_id, "camera_id")
    if err:
        return err
    try:
        response = await client.get(f"{_BASE}/{camera_id}/rtsps-stream")
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return _not_found(camera_id)
        raise
    streams = response.get("data", response) if isinstance(response, dict) else {}
    return {
        "camera_id": camera_id, "revealed": bool(reveal_urls),
        "streams": _mask_streams(streams, bool(reveal_urls)),
    }


async def create_rtsps_stream(
    client: UnifiClient, camera_id: str, qualities: list, confirm: bool = False,
) -> dict:
    """Create RTSPS stream URLs for a camera (Tier 2). qualities: list of high, medium, low, package.

    Anyone holding a stream URL can watch the camera. Returned URLs are masked;
    read them with get_rtsps_streams(reveal_urls=True) when needed.
    """
    err = check_id(camera_id, "camera_id")
    if err:
        return err
    wanted, err = _check_qualities(qualities)
    if err:
        return err
    camera, err = await _check_package(client, camera_id, wanted)
    if err:
        return err
    if not confirm:
        return {
            "preview": True, "action": "create_rtsps_stream", "camera_id": camera_id,
            "camera_name": camera.get("name"), "qualities": wanted,
            "message": "Creates live stream URLs that grant video access. Call again with confirm=True.",
        }
    response = await client.post(f"{_BASE}/{camera_id}/rtsps-stream", json={"qualities": wanted})
    if _is_empty(response):
        return _noop("create_rtsps_stream", camera_id, qualities=wanted)
    return _executed(
        client, "create_rtsps_stream", camera_id, _mask_streams(response, False), qualities=wanted,
    )


async def delete_rtsps_stream(
    client: UnifiClient, camera_id: str, qualities: list, confirm: bool = False,
) -> dict:
    """Delete RTSPS streams of a camera (Tier 2). qualities: list of high, medium, low, package.

    Anything using the removed stream URLs stops working.
    """
    err = check_id(camera_id, "camera_id")
    if err:
        return err
    wanted, err = _check_qualities(qualities)
    if err:
        return err
    camera, err = await _check_package(client, camera_id, wanted)
    if err:
        return err
    if not confirm:
        return {
            "preview": True, "action": "delete_rtsps_stream", "camera_id": camera_id,
            "camera_name": camera.get("name"), "qualities": wanted,
            "impact": "Any recorder or viewer using these stream URLs will lose the stream.",
            "message": "Call again with confirm=True to delete these streams.",
        }
    query = "&".join(f"qualities={q}" for q in wanted)
    response = await client.delete(f"{_BASE}/{camera_id}/rtsps-stream?{query}")
    return _executed(
        client, "delete_rtsps_stream", camera_id, _mask_streams(response, False), qualities=wanted,
    )


TOOLS = [
    ptz_camera, update_camera_settings, set_camera_led,
    disable_camera_mic_permanently, get_rtsps_streams,
    create_rtsps_stream, delete_rtsps_stream,
]
