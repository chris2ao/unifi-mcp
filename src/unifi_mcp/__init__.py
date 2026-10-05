"""chris2ao-unifi-mcp: Unified UniFi MCP server."""

import importlib.metadata

_DIST_NAME = "chris2ao-unifi-mcp"
_FALLBACK_VERSION = "0.0.0+unknown"


def _resolve_version() -> str:
    """Return the installed distribution version, or a fallback when not installed."""
    try:
        return importlib.metadata.version(_DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _FALLBACK_VERSION


__version__ = _resolve_version()
