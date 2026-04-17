"""UniFi Protect event tools.

Protect 7.0.x does not expose `/integration/v1/events` via the API-key surface
on this console. The endpoint returns 404 even with a valid local-console key
that succeeds against /cameras and /nvrs. Until UniFi adds events to the
Integration API on the running firmware, these tools return a structured
PRODUCT_UNAVAILABLE error so callers can route around them deliberately.
"""

from unifi_mcp.auth.client import UnifiClient


_UNAVAILABLE = {
    "error": True,
    "category": "PRODUCT_UNAVAILABLE",
    "message": (
        "Protect events are not exposed on this firmware via the API-key "
        "Integration API. Use the Protect mobile / web UI for live event review "
        "or capture snapshots via get_camera_snapshot."
    ),
}


async def list_motion_events(
    client: UnifiClient, camera_id: str | None = None, limit: int = 50,
) -> list[dict]:
    """List recent motion events. Currently unavailable via API key (see message)."""
    return [_UNAVAILABLE]


async def list_smart_detections(
    client: UnifiClient, camera_id: str | None = None, limit: int = 50,
) -> list[dict]:
    """List recent smart-detection events. Currently unavailable via API key."""
    return [_UNAVAILABLE]


TOOLS = [list_motion_events, list_smart_detections]
