"""Boundary validation helpers shared by tool modules.

Every checker returns None when the value is acceptable, or a VALIDATION_ERROR
dict (the same shape tools already return) describing the problem. Tools can
therefore write::

    err = check_id(device_id, "device_id")
    if err:
        return err
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_MAC_COLON_RE = re.compile(r"[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}")
_MAC_BARE_RE = re.compile(r"[0-9A-Fa-f]{12}")


def validation_error(message: str) -> dict:
    """Build the standard VALIDATION_ERROR response dict."""
    return {"error": True, "category": "VALIDATION_ERROR", "message": message}


def check_id(value: Any, field: str = "id") -> dict | None:
    """Validate an identifier that may be interpolated into a URL path.

    Accepts a non-empty string of at most 128 characters that starts with an
    alphanumeric character and contains only letters, digits, "_", ".", ":"
    or "-". Rejects path traversal ("..") explicitly.
    """
    if not isinstance(value, str) or not value:
        return validation_error(f"{field} must be a non-empty string.")
    if ".." in value or not _ID_RE.fullmatch(value):
        return validation_error(
            f"{field} contains invalid characters. Use only letters, digits, "
            "'_', '.', ':' or '-' (max 128 chars, no '..')."
        )
    return None


def _is_mac(value: str) -> bool:
    return bool(_MAC_COLON_RE.fullmatch(value) or _MAC_BARE_RE.fullmatch(value))


def check_mac(value: Any, field: str = "mac") -> dict | None:
    """Validate a MAC address (aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff or aabbccddeeff)."""
    if not isinstance(value, str) or not _is_mac(value):
        return validation_error(
            f"{field} must be a MAC address like aa:bb:cc:dd:ee:ff, "
            "aa-bb-cc-dd-ee-ff or aabbccddeeff."
        )
    return None


def normalize_mac(value: str) -> str:
    """Return the lowercase colon-separated form of a MAC address.

    Raises ValueError when the input is not a recognizable MAC address.
    """
    if not isinstance(value, str) or not _is_mac(value):
        raise ValueError(f"Not a MAC address: {value!r}")
    hex_only = re.sub(r"[:-]", "", value).lower()
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


def check_enum(value: Any, allowed: Iterable[Any], field: str) -> dict | None:
    """Validate that value is one of the allowed values."""
    allowed_list = list(allowed)
    if value not in allowed_list:
        shown = ", ".join(str(a) for a in allowed_list)
        return validation_error(f"{field} must be one of: {shown}. Got: {value!r}.")
    return None


def check_range(value: Any, lo: float, hi: float, field: str) -> dict | None:
    """Validate that value is a number (not bool) within [lo, hi] inclusive."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return validation_error(f"{field} must be a number between {lo} and {hi}.")
    if value != value or value < lo or value > hi:
        return validation_error(f"{field} must be between {lo} and {hi}. Got: {value}.")
    return None
