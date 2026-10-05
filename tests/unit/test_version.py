"""Package version is sourced from installed metadata, not hardcoded."""
import importlib.metadata

import unifi_mcp


def test_package_version_matches_metadata():
    assert unifi_mcp.__version__ == importlib.metadata.version("chris2ao-unifi-mcp")


def test_resolve_version_falls_back_when_not_installed(monkeypatch):
    def _missing(_name):
        raise importlib.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(importlib.metadata, "version", _missing)
    assert unifi_mcp._resolve_version() == "0.0.0+unknown"
