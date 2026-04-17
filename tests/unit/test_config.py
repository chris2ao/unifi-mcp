import os
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
