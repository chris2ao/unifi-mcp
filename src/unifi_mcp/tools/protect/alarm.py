"""UniFi Protect Alarm Manager tools: arm profiles, arm/disarm, alarm webhooks.

Uses the Integration API at /proxy/protect/integration/v1/ (spec 7.3.70).
Arming and disarming act on the whole system, so every write is Tier 2 and
previews carry an explicit impact warning.
"""

import re

from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.errors import UnifiError

GROUP = "security"

TIER2_TOOLS = {
    "arm_alarm": "protect_alarm",
    "disarm_alarm": "protect_alarm",
    "set_active_arm_profile": "protect_alarm",
    "create_arm_profile": "protect_alarm",
    "update_arm_profile": "protect_alarm",
    "delete_arm_profile": "protect_alarm",
    "trigger_alarm_webhook": "protect_alarm",
}

_BASE = "/proxy/protect/integration/v1"
_CACHE = "protect_alarm"
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ACTIVATION_DELAYS = (0, 60000, 300000, 600000)
_UPDATABLE = {
    "name", "automations", "schedules", "recordEverything", "activationDelay",
}
_ALIASES = {
    "record_everything": "recordEverything",
    "activation_delay": "activationDelay",
}


def _error(message: str, **extra) -> dict:
    return {"error": True, "category": "VALIDATION_ERROR", "message": message, **extra}


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
        if isinstance(data, dict):
            return [data]
        if response.get("id") or response.get("armMode"):
            return [response]
    return []


def _format_profile(p: dict) -> dict:
    return {
        "id": p.get("id"),
        "name": p.get("name"),
        "automations": p.get("automations", []),
        "schedules": p.get("schedules", []),
        "record_everything": p.get("recordEverything", False),
        "activation_delay_ms": p.get("activationDelay", 0),
        "creator": p.get("creator"),
        "created_at": p.get("createdAt"),
        "updated_at": p.get("updatedAt"),
    }


def _validate_fields(fields: dict) -> dict | None:
    """Validate (already camelCase) arm profile fields. Returns an error or None."""
    if "name" in fields:
        name = fields["name"]
        if not isinstance(name, str) or not 1 <= len(name) <= 255:
            return _error("name must be a string of 1-255 characters.")
    if "automations" in fields:
        autos = fields["automations"]
        if not isinstance(autos, list):
            return _error("automations must be a list of automation IDs.")
        for a in autos:
            if (bad := _check_id(a, "automation ID")):
                return bad
    if "schedules" in fields:
        scheds = fields["schedules"]
        ok = isinstance(scheds, list) and all(
            isinstance(s, dict) and set(s) == {"start", "end"}
            and all(isinstance(s[k], str) and s[k] for k in ("start", "end"))
            for s in scheds
        )
        if not ok:
            return _error(
                "schedules must be a list of {\"start\": cron, \"end\": cron} objects.",
            )
    if "recordEverything" in fields and not isinstance(fields["recordEverything"], bool):
        return _error("recordEverything must be a boolean.")
    if "activationDelay" in fields:
        delay = fields["activationDelay"]
        if isinstance(delay, bool) or delay not in _ACTIVATION_DELAYS:
            return _error(
                f"activationDelay must be one of {list(_ACTIVATION_DELAYS)} (milliseconds).",
            )
    return None


def _preview(action: str, message: str, impact: str | None = None, **params) -> dict:
    out = {"preview": True, "action": action, **params, "message": message}
    if impact:
        out["impact"] = impact
    return out


def _executed(action: str, response, expect_body: bool = False, **extra) -> dict:
    if expect_body and not response:
        return {
            "executed": False, "action": action, **extra, "response": response,
            "message": (
                "The console returned HTTP 200 with an empty body, which usually "
                "means the request was ignored. Verify the target and retry."
            ),
        }
    return {"executed": True, "action": action, **extra, "response": response}


async def list_arm_profiles(client: UnifiClient) -> list[dict]:
    """List Alarm Manager arm profiles (name, automations, schedules, activation delay)."""
    response = await client.get(
        f"{_BASE}/arm-profiles", cache_category=_CACHE, cache_ttl=15.0,
    )
    return [_format_profile(p) for p in _as_list(response)]


async def get_alarm_status(client: UnifiClient) -> dict:
    """Get the current alarm arm state: status (arming/armed/breach/disabled), timestamps, breach details.

    Timestamps are Unix epoch milliseconds. arm_profile_id is null when the
    firmware does not expose the active profile.
    """
    nvrs = _as_list(await client.get(f"{_BASE}/nvrs"))
    if not nvrs:
        return {
            "error": True, "category": "NOT_FOUND",
            "message": "No NVR returned by Protect; cannot read alarm status.",
        }
    nvr = nvrs[0]
    mode = nvr.get("armMode")
    if not isinstance(mode, dict):
        return {
            "error": True, "category": "PRODUCT_UNAVAILABLE",
            "message": (
                "Alarm Manager arm state is not exposed by this Protect firmware, "
                "or the alarm manager is not local."
            ),
        }
    return {
        "nvr_id": nvr.get("id"),
        "status": mode.get("status"),
        "arm_profile_id": mode.get("armProfileId"),
        "armed_at": mode.get("armedAt"),
        "will_be_armed_at": mode.get("willBeArmedAt"),
        "breach_detected_at": mode.get("breachDetectedAt"),
        "breach_event_count": mode.get("breachEventCount", 0),
        "breach_trigger_event_id": mode.get("breachTriggerEventId"),
        "breach_event_id": mode.get("breachEventId"),
    }


async def _context(client: UnifiClient) -> dict:
    """Best-effort current status and active profile id (read-only)."""
    ctx: dict = {}
    try:
        status = await get_alarm_status(client)
    except UnifiError:
        return ctx
    if status.get("error"):
        return ctx
    ctx["current_status"] = status.get("status")
    profile_id = status.get("arm_profile_id")
    if profile_id:
        ctx["active_profile_id"] = profile_id
    return ctx


async def _profile_context(client: UnifiClient, ctx: dict) -> dict:
    """Add the active profile name and the available profiles (best effort)."""
    try:
        profiles = await list_arm_profiles(client)
    except UnifiError:
        return ctx
    named = [p for p in profiles if p.get("id") == ctx.get("active_profile_id")]
    return {
        **ctx,
        **({"active_profile_name": named[0].get("name")} if named else {}),
        "available_profiles": [{"id": p.get("id"), "name": p.get("name")} for p in profiles],
    }


def _already(action: str, state: str) -> dict:
    return {
        "executed": False, "action": action, "current_status": state,
        "message": f"No change: the alarm is already {state}.",
    }


async def arm_alarm(client: UnifiClient, confirm: bool = False) -> dict:
    """Arm the Protect alarm using the active arm profile. Tier 2, requires confirm=True after preview.

    The preview names the current status and the active profile. Returns a
    no-op result (executed=False) when the alarm is already armed or arming.
    """
    ctx = await _context(client)
    if ctx.get("current_status") in ("armed", "arming"):
        return _already("arm_alarm", ctx["current_status"])
    if not confirm:
        ctx = await _profile_context(client, ctx)
        return _preview(
            "arm_alarm",
            "Will arm the alarm. Call again with confirm=True to execute.",
            impact=(
                "Arming activates alarm automations: breaches can trigger sirens, "
                "notifications and recording. It starts after the profile's activation delay."
            ),
            **ctx,
        )
    response = await client.post(f"{_BASE}/arm-profiles/enable")
    client.invalidate_cache(_CACHE)
    return _executed("arm_alarm", response)


async def disarm_alarm(client: UnifiClient, confirm: bool = False) -> dict:
    """Disarm the Protect alarm. Tier 2, requires confirm=True after preview.

    The preview shows the current status. Returns a no-op result
    (executed=False) when the alarm is already disabled.
    """
    ctx = await _context(client)
    if ctx.get("current_status") == "disabled":
        return _already("disarm_alarm", "disabled")
    if not confirm:
        return _preview(
            "disarm_alarm",
            "Will disarm the alarm. Call again with confirm=True to execute.",
            impact=(
                "Disarming stops breach detection and alarm automations until the "
                "system is armed again. The property is unprotected while disarmed."
            ),
            **ctx,
        )
    response = await client.post(f"{_BASE}/arm-profiles/disable")
    client.invalidate_cache(_CACHE)
    return _executed("disarm_alarm", response)


async def set_active_arm_profile(
    client: UnifiClient, profile_id: str, confirm: bool = False,
) -> dict:
    """Select which arm profile is active (does not arm). Tier 2, requires confirm=True after preview."""
    if (bad := _check_id(profile_id, "profile_id")):
        return bad
    if not confirm:
        return _preview(
            "set_active_arm_profile",
            f"Will make arm profile {profile_id} the active profile. "
            "Call again with confirm=True to execute.",
            impact=(
                "The next arm uses this profile's automations, schedules and delay. "
                "If the alarm is already armed, behavior may change immediately."
            ),
            profile_id=profile_id,
        )
    response = await client.patch(
        f"{_BASE}/arm-profiles/settings", json={"armProfileId": profile_id},
    )
    client.invalidate_cache(_CACHE)
    return _executed("set_active_arm_profile", response, profile_id=profile_id)


async def create_arm_profile(
    client: UnifiClient,
    name: str,
    automations: list[str] | None = None,
    schedules: list[dict] | None = None,
    record_everything: bool | None = None,
    activation_delay: int | None = None,
    confirm: bool = False,
) -> dict:
    """Create an arm profile. Defaults: no automations, no schedules, record_everything=False, activation_delay=0.

    schedules is a list of {"start": cron, "end": cron}. activation_delay is
    milliseconds: 0, 60000, 300000 or 600000. Tier 2, requires confirm=True.
    """
    body = {
        "name": name,
        "automations": [] if automations is None else automations,
        "schedules": [] if schedules is None else schedules,
        "recordEverything": False if record_everything is None else record_everything,
        "activationDelay": 0 if activation_delay is None else activation_delay,
    }
    if (bad := _validate_fields(body)):
        return bad
    if not confirm:
        return _preview(
            "create_arm_profile",
            f"Will create arm profile '{name}'. Call again with confirm=True to execute.",
            impact="Linked automations may fire sirens and notifications when the profile is armed.",
            profile=body,
        )
    response = await client.post(f"{_BASE}/arm-profiles", json=body)
    client.invalidate_cache(_CACHE)
    return _executed("create_arm_profile", response, profile=body)


async def update_arm_profile(
    client: UnifiClient, profile_id: str, updates: dict, confirm: bool = False,
) -> dict:
    """Update an arm profile. updates may contain name, automations, schedules, recordEverything, activationDelay (ms). Tier 2."""
    if (bad := _check_id(profile_id, "profile_id")):
        return bad
    if not isinstance(updates, dict) or not updates:
        return _error("updates must be a non-empty dict.")
    body = {_ALIASES.get(k, k): v for k, v in updates.items()}
    unknown = sorted(set(body) - _UPDATABLE)
    if unknown:
        return _error(
            f"Unsupported fields: {unknown}. Allowed: {sorted(_UPDATABLE)}.",
        )
    if (bad := _validate_fields(body)):
        return bad
    if not confirm:
        return _preview(
            "update_arm_profile",
            f"Will update arm profile {profile_id}. Call again with confirm=True to execute.",
            impact="Changing automations or schedules alters what an armed system does on a breach.",
            profile_id=profile_id,
            updates=body,
        )
    response = await client.patch(f"{_BASE}/arm-profiles/{profile_id}", json=body)
    client.invalidate_cache(_CACHE)
    return _executed("update_arm_profile", response, expect_body=True, profile_id=profile_id)


async def delete_arm_profile(
    client: UnifiClient, profile_id: str, confirm: bool = False,
) -> dict:
    """Delete an arm profile. Irreversible. Tier 2, requires confirm=True after preview."""
    if (bad := _check_id(profile_id, "profile_id")):
        return bad
    if not confirm:
        return _preview(
            "delete_arm_profile",
            f"Will delete arm profile {profile_id}. This is irreversible. "
            "Call again with confirm=True to execute.",
            impact="If this is the active profile, the alarm may be left without a profile.",
            profile_id=profile_id,
        )
    response = await client.delete(f"{_BASE}/arm-profiles/{profile_id}")
    client.invalidate_cache(_CACHE)
    return _executed("delete_arm_profile", response, profile_id=profile_id)


async def trigger_alarm_webhook(
    client: UnifiClient, webhook_id: str, confirm: bool = False,
) -> dict:
    """Fire an Alarm Manager webhook trigger by its ID. Tier 2, requires confirm=True after preview.

    The ID is a user-defined trigger string. Protect answers 204 whether or not
    any alarm uses it, so success only means the trigger was sent; only alarms
    configured with this trigger ID will run.
    """
    if (bad := _check_id(webhook_id, "webhook_id")):
        return bad
    if not confirm:
        return _preview(
            "trigger_alarm_webhook",
            f"Will trigger alarm webhook {webhook_id}. Call again with confirm=True to execute.",
            impact=(
                "Runs every Alarm Manager automation bound to this webhook, which "
                "may sound sirens, send notifications or start recording."
            ),
            webhook_id=webhook_id,
        )
    try:
        response = await client.post(f"{_BASE}/alarm-manager/webhook/{webhook_id}")
    except UnifiError as e:
        if e.category == "NOT_FOUND":
            return {
                "error": True, "category": "NOT_FOUND",
                "message": f"No alarm webhook found with id '{webhook_id}'",
                "webhook_id": webhook_id,
            }
        raise
    client.invalidate_cache(_CACHE)
    return {
        **_executed("trigger_alarm_webhook", response, webhook_id=webhook_id),
        "note": (
            "Sent to Alarm Manager. Only alarms configured with this trigger ID "
            "will run; a successful response does not confirm that any alarm matched."
        ),
    }


TOOLS = [
    list_arm_profiles,
    get_alarm_status,
    arm_alarm,
    disarm_alarm,
    set_active_arm_profile,
    create_arm_profile,
    update_arm_profile,
    delete_arm_profile,
    trigger_alarm_webhook,
]
