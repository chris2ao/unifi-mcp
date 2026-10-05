"""UniFi Protect NVR / system device tools (read-only)."""

from unifi_mcp.auth.client import UnifiClient


def _summarize_nvr(nvr: dict) -> dict:
    return {
        "id": nvr.get("id"),
        "name": nvr.get("name"),
        "model_key": nvr.get("modelKey"),
        "version": nvr.get("version") or nvr.get("firmwareVersion"),
        "doorbell_settings": nvr.get("doorbellSettings", {}),
    }


async def list_nvrs(client: UnifiClient) -> list[dict]:
    """List Protect NVRs (Network Video Recorders) registered to this console.

    The Protect Integration API returns the NVR record as a single object on
    consoles with one recorder (e.g., UDM Pro). This tool always returns a list
    for callers that expect a uniform shape.
    """
    response = await client.get(
        "/proxy/protect/integration/v1/nvrs",
        cache_category="protect_nvrs", cache_ttl=60.0,
    )
    if isinstance(response, list):
        nvrs = response
    elif isinstance(response, dict) and "data" in response:
        nvrs = response["data"] if isinstance(response["data"], list) else [response["data"]]
    elif isinstance(response, dict):
        nvrs = [response]
    else:
        nvrs = []
    return [_summarize_nvr(n) for n in nvrs]


async def get_nvr_stats(client: UnifiClient) -> dict:
    """Get the full NVR record (storage, system stats, doorbell settings)."""
    response = await client.get(
        "/proxy/protect/integration/v1/nvrs",
        cache_category="protect_nvrs", cache_ttl=15.0,
    )
    if isinstance(response, list):
        return response[0] if response else {}
    return response


_REBOOT_UNAVAILABLE = {
    "error": True,
    "category": "PRODUCT_UNAVAILABLE",
    "message": (
        "Camera reboot is not available through the Protect Integration API "
        "(verified on Protect 7.2.105, spec v7.3.70): there is no reboot "
        "endpoint for cameras or NVRs. Reboot cameras from the Protect web or "
        "mobile UI."
    ),
}


async def reboot_camera(
    client: UnifiClient, camera_id: str, confirm: bool = False,
) -> dict:
    """Reboot a Protect camera. Currently unavailable via API key."""
    return dict(_REBOOT_UNAVAILABLE)


reboot_camera.never_previews = True  # stub: no preview is ever produced, see server._run_guarded


TOOLS = [list_nvrs, get_nvr_stats, reboot_camera]
