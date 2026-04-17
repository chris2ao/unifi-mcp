"""Integration test configuration.

These tests require a live UniFi console. Set UNIFI_HOST and UNIFI_API_KEY
in the environment before running. Tests are skipped automatically if those
variables are absent.

Run with:
    uv run pytest tests/integration/ -m integration -v -s
"""
import os
import pytest
from unifi_mcp.config import UnifiConfig
from unifi_mcp.cache import TTLCache
from unifi_mcp.auth.client import UnifiClient
from unifi_mcp.auth.discovery import DiscoveryRegistry


@pytest.fixture
def live_config():
    """Requires UNIFI_HOST and UNIFI_API_KEY to be set in environment."""
    if not os.getenv("UNIFI_HOST") or not os.getenv("UNIFI_API_KEY"):
        pytest.skip("UNIFI_HOST and UNIFI_API_KEY required for integration tests")
    return UnifiConfig()


@pytest.fixture
async def live_client(live_config):
    """Real UnifiClient connected to the live console."""
    cache = TTLCache()
    discovery = DiscoveryRegistry()
    client = UnifiClient(live_config, cache, discovery)
    yield client
    await client.close()
