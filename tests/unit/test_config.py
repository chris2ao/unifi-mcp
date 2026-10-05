import pytest
from unifi_mcp.config import UnifiConfig


def test_config_loads_required_env_vars(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    config = UnifiConfig()
    assert config.unifi_host == "https://192.168.1.1"
    assert config.unifi_api_key == "test-key-123"


def test_config_defaults(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    config = UnifiConfig()
    assert config.unifi_site == "default"
    assert config.unifi_verify_ssl is False


def test_config_custom_site(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.setenv("UNIFI_SITE", "office")
    config = UnifiConfig()
    assert config.unifi_site == "office"


def test_config_ssl_verification(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.setenv("UNIFI_VERIFY_SSL", "true")
    config = UnifiConfig()
    assert config.unifi_verify_ssl is True


def test_config_missing_host_raises(monkeypatch):
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.delenv("UNIFI_HOST", raising=False)
    with pytest.raises(Exception):
        UnifiConfig()


def test_config_missing_api_key_raises(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.delenv("UNIFI_API_KEY", raising=False)
    with pytest.raises(Exception):
        UnifiConfig()


def test_config_preview_ttl_default(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.delenv("UNIFI_PREVIEW_TTL_SECONDS", raising=False)
    config = UnifiConfig()
    assert config.unifi_preview_ttl_seconds == 600


def test_config_preview_ttl_override(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.setenv("UNIFI_PREVIEW_TTL_SECONDS", "120")
    config = UnifiConfig()
    assert config.unifi_preview_ttl_seconds == 120


@pytest.mark.parametrize("bad", ["0", "-5", "not-a-number"])
def test_config_preview_ttl_rejects_invalid(monkeypatch, bad):
    monkeypatch.setenv("UNIFI_HOST", "https://192.168.1.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.setenv("UNIFI_PREVIEW_TTL_SECONDS", bad)
    with pytest.raises(Exception):
        UnifiConfig()


# --- v0.6.0: UNIFI_TOOL_GROUPS ---

@pytest.fixture
def base_env(monkeypatch):
    monkeypatch.setenv("UNIFI_HOST", "https://192.0.2.1")
    monkeypatch.setenv("UNIFI_API_KEY", "test-key-123")
    monkeypatch.delenv("UNIFI_TOOL_GROUPS", raising=False)
    return monkeypatch


def test_tool_groups_unset_means_all(base_env):
    config = UnifiConfig()
    assert config.unifi_tool_groups is None
    assert config.tool_groups_for("network") is None
    assert config.tool_groups_for("protect") is None


def test_tool_groups_parsed_per_product(base_env):
    base_env.setenv("UNIFI_TOOL_GROUPS", "network:core,network:security,protect:cameras")
    config = UnifiConfig()
    assert config.tool_groups_for("network") == ["core", "security"]
    assert config.tool_groups_for("protect") == ["cameras"]
    # A product that is not mentioned loads every group.
    assert config.tool_groups_for("access") is None


def test_tool_groups_normalized_and_deduplicated(base_env):
    base_env.setenv("UNIFI_TOOL_GROUPS", " Network:Core , network:core,,PROTECT:all ")
    config = UnifiConfig()
    assert config.unifi_tool_groups == "network:core,protect:all"
    assert config.tool_groups_for("network") == ["core"]
    assert config.tool_groups_for("protect") == ["all"]


@pytest.mark.parametrize("blank", ["", "  ", ",,"])
def test_tool_groups_blank_is_unset(base_env, blank):
    base_env.setenv("UNIFI_TOOL_GROUPS", blank)
    assert UnifiConfig().unifi_tool_groups is None


@pytest.mark.parametrize("bad", [
    "core",                 # no product
    "cloud:cloud",          # not a loader product
    "network:",             # no group
    "network:core;protect:cameras",
    "network:../x",
    "network:1core",
])
def test_tool_groups_rejects_invalid_entries(base_env, bad):
    base_env.setenv("UNIFI_TOOL_GROUPS", bad)
    with pytest.raises(Exception, match="UNIFI_TOOL_GROUPS"):
        UnifiConfig()


def test_tool_groups_rejects_non_string():
    with pytest.raises(Exception, match="UNIFI_TOOL_GROUPS"):
        UnifiConfig(unifi_host="https://192.0.2.1", unifi_api_key="k", unifi_tool_groups=5)
