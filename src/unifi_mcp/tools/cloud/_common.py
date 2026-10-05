"""Shared helpers for cloud tools: input validation and response unwrapping."""

import re
from datetime import datetime

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,255}$")
RFC3339_HINT = "RFC3339 timestamp such as 2024-06-30T13:35:00Z"


def validation_error(message: str) -> dict:
    return {"error": True, "category": "VALIDATION_ERROR", "message": message}


def check_id(value: object, name: str) -> dict | None:
    """Return a validation error dict if `value` is unsafe to put in a URL path."""
    if not isinstance(value, str) or not _ID_RE.fullmatch(value) or ".." in value:
        return validation_error(
            f"{name} must be 1-256 characters of letters, digits, '_', '-', '.', ':' starting with a letter or digit (no '/', '..', '?', '#', spaces)"
        )
    return None


def check_timestamp(value: object, name: str) -> dict | None:
    if not isinstance(value, str):
        return validation_error(f"{name} must be an {RFC3339_HINT}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return validation_error(f"{name} must be an {RFC3339_HINT}")
    if "T" not in value.upper() or parsed.tzinfo is None:
        return validation_error(f"{name} must be an {RFC3339_HINT}")
    return None


def unwrap(response: object) -> object:
    """Return the `data` payload of a Site Manager envelope (or the response itself)."""
    if isinstance(response, dict) and "data" in response:
        return response["data"]
    return response


def as_list(response: object) -> list:
    data = unwrap(response)
    if isinstance(data, list):
        return data
    return [data] if data else []
