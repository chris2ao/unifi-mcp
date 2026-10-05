"""Validation of camera PATCH settings against the Protect spec (7.3.70).

Helper for camera_controls.py. Exposes no MCP tools.
"""

from unifi_mcp.validation import check_enum, check_range, validation_error

GROUP = "cameras"
TIER2_TOOLS: dict[str, str] = {}
TOOLS: list = []

_PATCH_VIDEO_MODES = ("default", "highFps", "sport", "slowShutter", "lprReflex", "lprNoneReflex")
_VIDEO_MODES = ("default", "highFps", "homekit", "sport", "slowShutter", "lprReflex", "lprNoneReflex")
_HDR_TYPES = ("auto", "on", "off")
_OVERLAYS = ("topLeft", "topMiddle", "topRight", "bottomLeft", "bottomMiddle", "bottomRight")
_OBJECT_TYPES = ("person", "vehicle", "package", "licensePlate", "face", "animal")
_AUDIO_TYPES = (
    "alrmSmoke", "alrmCmonx", "alrmSiren", "alrmBabyCry", "alrmSpeak",
    "alrmBark", "alrmBurglar", "alrmCarHorn", "alrmGlassBreak",
)
_LCD_TYPES = ("DO_NOT_DISTURB", "LEAVE_PACKAGE_AT_DOOR", "CUSTOM_MESSAGE", "IMAGE")
_OSD_BOOLS = ("isNameEnabled", "isDateEnabled", "isLogoEnabled", "isDebugEnabled")
_LED_BOOLS = ("isEnabled", "welcomeLed", "floodLed")
ALLOWED_SETTINGS = (
    "osdSettings", "ledSettings", "lcdMessage", "micVolume", "videoMode",
    "hdrType", "smartDetectSettings",
)


def _check_bool_map(value, keys: tuple, field: str) -> dict | None:
    if not isinstance(value, dict) or not value:
        return validation_error(f"{field} must be a non-empty object.")
    unknown = sorted(set(value) - set(keys))
    if unknown:
        return validation_error(f"{field} has unknown keys: {', '.join(unknown)}. Allowed: {', '.join(keys)}.")
    for key, val in value.items():
        if not isinstance(val, bool) and not (field == "osdSettings" and key == "overlayLocation"):
            return validation_error(f"{field}.{key} must be true or false.")
    return None


def _check_osd(value) -> dict | None:
    keys = _OSD_BOOLS + ("overlayLocation",)
    if isinstance(value, dict) and "overlayLocation" in value:
        err = check_enum(value["overlayLocation"], _OVERLAYS, "osdSettings.overlayLocation")
        if err:
            return err
    return _check_bool_map(value, keys, "osdSettings")


def _check_lcd(value) -> dict | None:
    if not isinstance(value, dict) or "type" not in value:
        return validation_error("lcdMessage must be an object with a 'type'.")
    unknown = sorted(set(value) - {"type", "resetAt", "text"})
    if unknown:
        return validation_error(f"lcdMessage has unknown keys: {', '.join(unknown)}.")
    err = check_enum(value["type"], _LCD_TYPES, "lcdMessage.type")
    if err:
        return err
    reset = value.get("resetAt")
    if reset is not None and (isinstance(reset, bool) or not isinstance(reset, (int, float))):
        return validation_error("lcdMessage.resetAt must be a UNIX timestamp number or null.")
    if value["type"] in ("CUSTOM_MESSAGE", "IMAGE") and not isinstance(value.get("text"), str):
        return validation_error(f"lcdMessage.text is required (string) for type {value['type']}.")
    return None


def _check_list(value, allowed, supported, field: str) -> dict | None:
    if not isinstance(value, list):
        return validation_error(f"{field} must be a list.")
    for item in value:
        err = check_enum(item, allowed, field)
        if err:
            return err
        if supported is not None and item not in supported:
            return validation_error(
                f"{field} value {item!r} is not supported by this camera. "
                f"Supported: {', '.join(supported) or 'none'}."
            )
    return None


def _check_smart(value, flags: dict) -> dict | None:
    if not isinstance(value, dict) or not value:
        return validation_error("smartDetectSettings must be a non-empty object.")
    unknown = sorted(set(value) - {"objectTypes", "audioTypes"})
    if unknown:
        return validation_error(f"smartDetectSettings has unknown keys: {', '.join(unknown)}.")
    checks = (
        ("objectTypes", _OBJECT_TYPES, flags.get("smartDetectTypes")),
        ("audioTypes", _AUDIO_TYPES, flags.get("smartDetectAudioTypes")),
    )
    for key, allowed, supported in checks:
        if key in value:
            err = _check_list(value[key], allowed, supported, f"smartDetectSettings.{key}")
            if err:
                return err
    return None


def validate_settings(settings, camera: dict) -> dict | None:
    """Validate a PATCH settings dict against the spec allow-list and camera flags."""
    if not isinstance(settings, dict) or not settings:
        return validation_error("settings must be a non-empty object.")
    if "name" in settings:
        return validation_error("Use update_camera_name to rename a camera; 'name' is not accepted here.")
    unknown = sorted(set(settings) - set(ALLOWED_SETTINGS))
    if unknown:
        return validation_error(
            f"Unknown settings keys: {', '.join(unknown)}. The console rejects them "
            f"(AJV_PARSE_ERROR). Allowed: {', '.join(ALLOWED_SETTINGS)}."
        )
    flags = camera.get("featureFlags") or {}
    camera_modes = flags.get("videoModes")
    modes = [m for m in (camera_modes or _VIDEO_MODES) if m in _PATCH_VIDEO_MODES]
    checks = {
        "osdSettings": _check_osd,
        "ledSettings": lambda v: _check_bool_map(v, _LED_BOOLS, "ledSettings"),
        "lcdMessage": _check_lcd,
        "micVolume": lambda v: check_range(v, 1, 100, "micVolume"),
        "videoMode": lambda v: check_enum(v, modes, "videoMode"),
        "hdrType": lambda v: check_enum(v, _HDR_TYPES, "hdrType"),
        "smartDetectSettings": lambda v: _check_smart(v, flags),
    }
    for key, value in settings.items():
        err = checks[key](value)
        if err:
            return err
    return None


