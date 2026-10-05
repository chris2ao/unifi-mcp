"""Generic UniFi Protect accessory device tools.

One set of four tools covers every accessory kind in the Protect Integration
API (spec 7.3.70) instead of about thirty per-kind tools: lights, sensors,
chimes, sirens, relays, speakers, bridges, link stations, alarm hubs and fobs.
Also provides a minimal Protect user listing.

Updates are limited to a per-kind allow-list built from each kind's PATCH
schema. Actions (siren, speaker, relay, alarm hub) are disruptive, so they are
Tier 2 with explicit impact warnings.
"""

import re

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError
from unifi_mcp.validation import check_enum, check_id, check_range, validation_error

GROUP = "devices"

TIER2_TOOLS = {
    "update_protect_device": "protect_devices",
    "run_protect_device_action": "protect_devices",
}

_BASE = "/proxy/protect/integration/v1"
_CACHE = "protect_devices"

KINDS = (
    "lights", "sensors", "chimes", "sirens", "relays",
    "speakers", "bridges", "link-stations", "alarm-hubs", "fobs",
)

# Top-level PATCH properties per kind (from each /v1/{kind}/{id} PATCH schema).
PATCH_FIELDS = {
    "lights": {"name", "isLightForceEnabled", "lightModeSettings", "lightDeviceSettings"},
    "sensors": {
        "name", "lightSettings", "humiditySettings", "temperatureSettings",
        "motionSettings", "glassBreakSettings", "scheduleMode", "armProfileIds",
        "hasCustomSensitivityWhenArmed", "alarmSettings",
    },
    "chimes": {"name", "cameraIds", "ringSettings"},
    "sirens": {"name", "volume", "ledSettings"},
    "relays": {"name", "ledSettings"},
    "speakers": {"name", "volume", "micVolume", "isMicEnabled"},
    "bridges": {"name"},
    "link-stations": {"name"},
    "alarm-hubs": {"name"},
    "fobs": {"name"},
}

# Allowed actions per kind and whether the action needs an output id.
ACTIONS = {
    "sirens": {"play": False, "stop": False, "test-sound": False},
    "speakers": {"test-sound": False},
    "relays": {"activate": True},
    "alarm-hubs": {"trigger": True},
}

_IMPACT = {
    "sirens": "IMPACT: sirens are loud (up to full volume) and may alarm people or pets nearby.",
    "speakers": "IMPACT: the speaker will emit a test sound audible to anyone nearby.",
    "relays": (
        "IMPACT: relay outputs can open gates, unlock doors or switch connected "
        "equipment. Confirm the output is safe to actuate."
    ),
    "alarm-hubs": (
        "IMPACT: alarm hub outputs can sound sirens or switch connected equipment. "
        "Confirm the output is safe to trigger."
    ),
}

_SECRET_RE = re.compile(r"token|secret|password|psk|apikey|api_key|rtsp", re.IGNORECASE)
_SIREN_DURATIONS = (5, 10, 20, 30)


def _as_list(response) -> list[dict]:
    if isinstance(response, list):
        return [r for r in response if isinstance(r, dict)]
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        if isinstance(data, dict):
            return [data]
        if response.get("id"):
            return [response]
    return []


def _scrub(value):
    """Return a copy with secret-looking keys (tokens, passwords, RTSPS) removed."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not _SECRET_RE.search(str(k))}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _check_kind(kind) -> dict | None:
    return check_enum(kind, KINDS, "kind")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


async def list_protect_devices(client: UnifiClient, kind: str) -> list[dict]:
    """List Protect accessory devices of one kind (read-only).

    kind: lights, sensors, chimes, sirens, relays, speakers, bridges,
    link-stations, alarm-hubs or fobs. Returns each device record (id, name,
    state, mac, kind-specific settings and outputs). Use get_protect_device for
    one device. Cameras and NVRs have their own tools.
    """
    err = _check_kind(kind)
    if err:
        return [err]
    items = await client.get_all_pages(
        f"{_BASE}/{kind}", cache_category=_CACHE, cache_ttl=30.0,
    )
    return [_scrub(i) for i in items if isinstance(i, dict)]


async def get_protect_device(client: UnifiClient, kind: str, device_id: str) -> dict:
    """Get one Protect accessory device by kind and id (read-only).

    kind: lights, sensors, chimes, sirens, relays, speakers, bridges,
    link-stations, alarm-hubs or fobs. device_id comes from list_protect_devices.
    """
    err = _check_kind(kind) or check_id(device_id, "device_id")
    if err:
        return err
    try:
        response = await client.get(f"{_BASE}/{kind}/{device_id}")
    except UnifiError as e:
        if str(getattr(e, "category", "")) != "NOT_FOUND":
            raise
        response = None
    records = _as_list(response)
    if not records:
        return {
            "error": True, "category": "NOT_FOUND",
            "message": f"No {kind} device found with id '{device_id}'.",
            "kind": kind, "device_id": device_id,
        }
    return _scrub(records[0])


def _validate_settings(kind: str, settings) -> dict | None:
    if not isinstance(settings, dict) or not settings:
        return validation_error("settings must be a non-empty object of fields to change.")
    allowed = PATCH_FIELDS[kind]
    unknown = sorted(set(settings) - allowed)
    if unknown:
        return validation_error(
            f"Unsupported field(s) for {kind}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}."
        )
    if "name" in settings and (not isinstance(settings["name"], str) or not settings["name"].strip()):
        return validation_error("name must be a non-empty string.")
    for key, lo in (("volume", 1 if kind == "sirens" else 0), ("micVolume", 0)):
        if key in settings:
            if not _is_int(settings[key]):
                return validation_error(f"{key} must be an integer.")
            err = check_range(settings[key], lo, 100, key)
            if err:
                return err
    if "isMicEnabled" in settings and not isinstance(settings["isMicEnabled"], bool):
        return validation_error("isMicEnabled must be a boolean.")
    return None


def _impact_for_update(kind: str, settings: dict) -> str | None:
    if kind == "speakers" and settings.get("isMicEnabled") is False:
        return "IMPACT: disabling the speaker microphone stops audio capture from this device."
    return None


async def update_protect_device(
    client: UnifiClient, kind: str, device_id: str, settings: dict,
    confirm: bool = False,
) -> dict:
    """Update settings on a Protect accessory device. Requires confirm=True after previewing.

    kind: lights, sensors, chimes, sirens, relays, speakers, bridges,
    link-stations, alarm-hubs or fobs. settings: a partial object limited to the
    fields the Protect API allows for that kind (for example name for any kind,
    volume for sirens 1-100, volume/micVolume 0-100 for speakers). The preview
    shows current vs proposed values.
    """
    err = _check_kind(kind) or check_id(device_id, "device_id") or _validate_settings(kind, settings)
    if err:
        return err
    if not confirm:
        current = await get_protect_device(client, kind, device_id)
        if current.get("error"):
            return current
        preview = {
            "preview": True, "action": "update_protect_device",
            "kind": kind, "device_id": device_id,
            "current": {k: current.get(k) for k in settings},
            "proposed": dict(settings),
            "message": (
                f"Will update {kind} device {device_id}. "
                "Call again with confirm=True to execute."
            ),
        }
        impact = _impact_for_update(kind, settings)
        return {**preview, "impact": impact} if impact else preview
    response = await client.patch(f"{_BASE}/{kind}/{device_id}", json=dict(settings))
    client.invalidate_cache(_CACHE)
    if not response:
        return {
            "executed": False, "action": "update_protect_device",
            "kind": kind, "device_id": device_id, "response": response,
            "message": (
                "Protect returned an empty response, which usually means nothing "
                "changed. Verify with get_protect_device."
            ),
        }
    return {"executed": True, "action": "update_protect_device", "response": _scrub(response)}


def _action_body(kind: str, action: str, options: dict) -> tuple[dict | None, dict | None]:
    """Validate options for an action and return (body, error)."""
    allowed = {
        ("sirens", "play"): {"duration"},
        ("sirens", "test-sound"): {"volume"},
        ("speakers", "test-sound"): {"volume"},
        ("relays", "activate"): {"state", "pulseDuration", "toggle"},
        ("alarm-hubs", "trigger"): {"enable", "delay", "duration", "toggle"},
    }.get((kind, action), set())
    unknown = sorted(set(options) - allowed)
    if unknown:
        return None, validation_error(
            f"Unsupported option(s) for {kind} {action}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed)) or 'none'}."
        )
    err = _check_option_values(options, kind)
    if err:
        return None, err
    err = _check_toggle(kind, action, options)
    if err:
        return None, err
    body = {k: v for k, v in options.items() if k != "toggle"}
    return body, None


_STATE_FIELD = {("relays", "activate"): "state", ("alarm-hubs", "trigger"): "enable"}


def _check_toggle(kind: str, action: str, options: dict) -> dict | None:
    """Relays and alarm hubs toggle when no state is given, so make that explicit."""
    field = _STATE_FIELD.get((kind, action))
    if field is None:
        return None
    if "toggle" in options and not isinstance(options["toggle"], bool):
        return validation_error("toggle must be a boolean.")
    if options.get("toggle") and field in options:
        return validation_error(f"Give either options.{field} or options.toggle=True, not both.")
    if field not in options and not options.get("toggle"):
        return validation_error(
            f"options.{field} is required for {kind} {action}. If {field} is omitted the "
            "output TOGGLES from its unknown current state; pass options={'toggle': True} "
            "to opt in to that explicitly."
        )
    return None


def _effect_line(kind: str, action: str, output_id, body: dict) -> str | None:
    if (kind, action) == ("relays", "activate"):
        if "state" not in body:
            return f"TOGGLE output {output_id} (current state unknown, may close an open gate)"
        extra = f" for {body['pulseDuration']} ms" if "pulseDuration" in body else ""
        return f"turn output {output_id} {body['state'].upper()}{extra}"
    if (kind, action) == ("alarm-hubs", "trigger"):
        if "enable" not in body:
            return f"TOGGLE output {output_id} (current state unknown)"
        return f"{'enable' if body['enable'] else 'disable'} output {output_id}"
    return None


def _check_option_values(options: dict, kind: str = "") -> dict | None:
    for key in ("pulseDuration", "delay", "duration"):
        if key == "duration" and kind == "sirens":
            continue  # siren play duration (seconds) is checked against its enum
        if key in options and (not _is_int(options[key]) or options[key] < 0):
            return validation_error(f"{key} must be a non-negative integer (milliseconds).")
    if "state" in options:
        err = check_enum(options["state"], ("on", "off"), "state")
        if err:
            return err
    if "enable" in options and not isinstance(options["enable"], bool):
        return validation_error("enable must be a boolean.")
    if "volume" in options:
        if not _is_int(options["volume"]):
            return validation_error("volume must be an integer.")
        return check_range(options["volume"], 1 if kind == "sirens" else 0, 100, "volume")
    return None


def _check_action(kind: str, action: str, output_id, options) -> dict | None:
    if kind not in ACTIONS:
        return validation_error(
            f"{kind} has no actions. Kinds with actions: {', '.join(ACTIONS)}."
        )
    err = check_enum(action, list(ACTIONS[kind]), "action")
    if err:
        return err
    if ACTIONS[kind][action]:
        if output_id is None:
            return validation_error(f"output_id is required for {kind} {action}.")
        return None
    if output_id is not None:
        return validation_error(f"output_id is not used by {kind} {action}.")
    return None


def _norm_output_id(value) -> tuple[int | None, dict | None]:
    """Normalize an output id (0, 1, '0', '1', ...) to a non-negative int."""
    if value is None:
        return None, None
    if isinstance(value, bool):
        return None, validation_error("output_id must be a non-negative integer.")
    if isinstance(value, int) and value >= 0:
        return value, None
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value), None
    return None, validation_error(
        "output_id must be a non-negative integer (for example 0 or 1), taken "
        "from relay outputs[].id or the alarm hub output keys."
    )


def _action_path(kind: str, device_id: str, action: str, output_id: int | None) -> str:
    if output_id is not None:
        return f"{_BASE}/{kind}/{device_id}/outputs/{output_id}/{action}"
    return f"{_BASE}/{kind}/{device_id}/{action}"


async def run_protect_device_action(
    client: UnifiClient, kind: str, device_id: str, action: str,
    output_id: int | str | None = None, options: dict | None = None,
    confirm: bool = False,
) -> dict:
    """Run a physical action on a Protect accessory. Requires confirm=True after previewing.

    Supported: sirens play (options.duration 5/10/20/30 seconds), stop and
    test-sound (options.volume 1-100); speakers test-sound (options.volume
    0-100); relays activate (needs output_id, an integer such as 0 or 1 from
    outputs[].id; options.state on/off is REQUIRED, options.pulseDuration ms);
    alarm-hubs trigger (needs output_id, options.enable true/false is REQUIRED,
    options.delay ms, options.duration ms). If state/enable is omitted the
    console toggles the output from its unknown current state, so pass
    options={"toggle": True} to opt in to that. Sirens are loud and relays can
    open gates or doors.
    """
    opts = {} if options is None else options
    output_id, oid_err = _norm_output_id(output_id)
    err = (
        _check_kind(kind) or check_id(device_id, "device_id") or oid_err
        or _check_action(kind, action, output_id, opts)
    )
    if not err and not isinstance(opts, dict):
        err = validation_error("options must be an object.")
    if not err and kind == "sirens" and "duration" in opts:
        err = check_enum(opts["duration"], _SIREN_DURATIONS, "duration")
    body, body_err = (None, err) if err else _action_body(kind, action, opts)
    if body_err:
        return body_err
    path = _action_path(kind, device_id, action, output_id)
    if not confirm:
        effect = _effect_line(kind, action, output_id, body or {})
        return {
            **({"effect": effect} if effect else {}),
            "preview": True, "action": "run_protect_device_action",
            "kind": kind, "device_id": device_id, "device_action": action,
            "output_id": output_id, "options": body,
            "impact": _IMPACT.get(kind, "IMPACT: this triggers a physical action."),
            "message": (
                f"Will run {action} on {kind} device {device_id}. "
                "Call again with confirm=True to execute."
            ),
        }
    response = await client.post(path, json=body or None)
    client.invalidate_cache(_CACHE)
    return {
        "executed": True, "action": "run_protect_device_action",
        "kind": kind, "device_id": device_id, "device_action": action,
        "response": response,
    }


def _min_user(item: dict, source: str) -> dict:
    name = item.get("name") or item.get("fullName") or ""
    return {
        "id": item.get("id"), "name": name, "email": item.get("email") or None,
        "status": item.get("status"), "source": source,
    }


async def list_protect_users(client: UnifiClient) -> dict:
    """List Protect users and UniFi Identity (ULP) users with minimal fields (read-only).

    Returns id, name, email and status (ULP users only) for each person. No
    tokens or credentials are returned. Use to map user ids seen elsewhere.
    """
    result: dict = {"users": [], "ulp_users": [], "errors": []}
    for key, path, source in (
        ("users", f"{_BASE}/users", "user"),
        ("ulp_users", f"{_BASE}/ulp-users", "ulp_user"),
    ):
        try:
            items = await client.get_all_pages(path, cache_category=_CACHE, cache_ttl=60.0)
        except UnifiError as e:
            result["errors"].append({"source": source, "message": str(e)})
            continue
        result[key] = [_min_user(i, source) for i in items if isinstance(i, dict)]
    return result


TOOLS = [
    list_protect_devices, get_protect_device, update_protect_device,
    run_protect_device_action, list_protect_users,
]
