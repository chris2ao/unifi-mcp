"""UniFi Protect camera tools (read-only).

Uses the Integration API at /proxy/protect/integration/v1/. All endpoints accept
the X-API-Key header that the MCP server already injects.
"""

import base64

from unifi_mcp.auth.client import UnifiClient


_CAMERA_FIELDS = (
    "id", "name", "mac", "modelKey", "state",
    "isMicEnabled", "videoMode", "hdrType",
)


def _summarize_camera(c: dict) -> dict:
    summary = {field: c.get(field) for field in _CAMERA_FIELDS}
    feature_flags = c.get("featureFlags", {})
    summary["smart_detect_types"] = feature_flags.get("smartDetectTypes", [])
    summary["has_hdr"] = feature_flags.get("hasHdr", False)
    summary["has_mic"] = feature_flags.get("hasMic", False)
    summary["has_speaker"] = feature_flags.get("hasSpeaker", False)
    return summary


async def list_cameras(client: UnifiClient) -> list[dict]:
    """List all UniFi Protect cameras with summary fields."""
    response = await client.get(
        "/proxy/protect/integration/v1/cameras",
        cache_category="protect_cameras", cache_ttl=15.0,
    )
    cameras = response if isinstance(response, list) else response.get("data", [])
    return [_summarize_camera(c) for c in cameras]


async def get_camera(client: UnifiClient, camera_id: str) -> dict:
    """Get full configuration and feature flags for a single camera."""
    response = await client.get(
        f"/proxy/protect/integration/v1/cameras/{camera_id}",
        cache_category="protect_cameras", cache_ttl=15.0,
    )
    if isinstance(response, dict) and response.get("error"):
        return response
    return response


async def get_camera_snapshot(client: UnifiClient, camera_id: str) -> dict:
    """Capture a current snapshot from the camera and return it as base64 JPEG.

    Note: the resulting payload can be ~500KB-2MB encoded, which is large for
    MCP tool responses. Prefer this only when image inspection is required.
    """
    image_bytes, content_type = await client.get_binary(
        f"/proxy/protect/integration/v1/cameras/{camera_id}/snapshot",
    )
    return {
        "camera_id": camera_id,
        "content_type": content_type or "image/jpeg",
        "size_bytes": len(image_bytes),
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
    }


async def list_liveviews(client: UnifiClient) -> list[dict]:
    """List configured Protect liveview layouts."""
    response = await client.get(
        "/proxy/protect/integration/v1/liveviews",
        cache_category="protect_liveviews", cache_ttl=60.0,
    )
    liveviews = response if isinstance(response, list) else response.get("data", [])
    return [
        {
            "id": lv.get("id"),
            "name": lv.get("name"),
            "is_default": lv.get("isDefault", False),
            "is_global": lv.get("isGlobal", False),
            "layout": lv.get("layout"),
            "slot_count": len(lv.get("slots", [])),
        }
        for lv in liveviews
    ]


async def update_camera_name(client: UnifiClient, camera_id: str, name: str) -> dict:
    """Rename a camera (Tier-1, cosmetic). Calls PATCH /cameras/{id}."""
    response = await client.patch(
        f"/proxy/protect/integration/v1/cameras/{camera_id}",
        json={"name": name},
    )
    client.invalidate_cache("protect_cameras")
    return {
        "executed": True,
        "action": "update_camera_name",
        "camera_id": camera_id,
        "name": response.get("name", name) if isinstance(response, dict) else name,
    }


# Integration API on Protect 7.0.104 does not expose recording-mode control,
# camera reboot, or PTZ. Every probe returns 404 or AJV schema rejection. These
# tools follow the project's PRODUCT_UNAVAILABLE precedent (see events.py).

_RECORDING_UNAVAILABLE = {
    "error": True,
    "category": "PRODUCT_UNAVAILABLE",
    "message": (
        "Camera recording-mode control is not exposed on this firmware via the "
        "API-key Integration API. PATCH /cameras/{id} rejects any "
        "recording-related property with AJV_PARSE_ERROR. Change recording mode "
        "in the Protect web/mobile UI."
    ),
}

_PTZ_UNAVAILABLE = {
    "error": True,
    "category": "PRODUCT_UNAVAILABLE",
    "message": (
        "PTZ control is not exposed on this firmware via the API-key "
        "Integration API. /cameras/{id}/ptz, /ptz/position, /ptz/presets all "
        "return 404 and PATCH rejects activePatrolSlot. Use the Protect "
        "web/mobile UI for PTZ movement and patrols."
    ),
}


async def set_camera_recording_mode(
    client: UnifiClient, camera_id: str, mode: str, confirm: bool = False,
) -> dict:
    """Set recording mode (always|motion|never). Currently unavailable via API key."""
    return _RECORDING_UNAVAILABLE


async def ptz_camera(
    client: UnifiClient, camera_id: str, pan: float | None = None,
    tilt: float | None = None, zoom: float | None = None, preset_id: str | None = None,
    confirm: bool = False,
) -> dict:
    """Move a PTZ camera. Currently unavailable via API key."""
    return _PTZ_UNAVAILABLE


TOOLS = [
    list_cameras, get_camera, get_camera_snapshot, list_liveviews,
    update_camera_name, set_camera_recording_mode, ptz_camera,
]
