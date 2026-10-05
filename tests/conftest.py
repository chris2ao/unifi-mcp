"""Shared test configuration."""
import os

import pytest


@pytest.fixture(scope="session")
def server():
    """Import unifi_mcp.server with placeholder env vars if the real ones are absent.

    The server builds its UnifiConfig at import time, so tests that import it must
    not depend on UNIFI_HOST / UNIFI_API_KEY being exported (CI sets neither).
    """
    with pytest.MonkeyPatch.context() as mp:
        if not os.environ.get("UNIFI_HOST"):
            mp.setenv("UNIFI_HOST", "https://192.0.2.1")
        if not os.environ.get("UNIFI_API_KEY"):
            mp.setenv("UNIFI_API_KEY", "test-key")
        import unifi_mcp.server as server_module
    return server_module
