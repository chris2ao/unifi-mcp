"""Configuration for the optional UniFi Site Manager cloud API."""

from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings

DEFAULT_CLOUD_BASE_URL = "https://api.ui.com"


def validate_cloud_base_url(value: str) -> str:
    """Return a normalized base URL, or raise ValueError if it is not https on ui.com."""
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise ValueError("UNIFI_CLOUD_BASE_URL must use https")
    if host != "ui.com" and not host.endswith(".ui.com"):
        raise ValueError("UNIFI_CLOUD_BASE_URL must be a host on ui.com")
    if parsed.username or parsed.password:
        raise ValueError("UNIFI_CLOUD_BASE_URL must not contain credentials")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{host}{port}{parsed.path.rstrip('/')}"


class CloudConfig(BaseSettings):
    """Cloud settings read from UNIFI_CLOUD_API_KEY and UNIFI_CLOUD_BASE_URL.

    The key is a unifi.ui.com cloud key and is distinct from the local console key.
    It is held as a SecretStr so it never appears in reprs or logs.
    """

    unifi_cloud_api_key: SecretStr | None = Field(default=None, repr=False)
    unifi_cloud_base_url: str = DEFAULT_CLOUD_BASE_URL

    model_config = {"env_prefix": "", "case_sensitive": False, "extra": "ignore"}

    @field_validator("unifi_cloud_base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        return validate_cloud_base_url(value)

    @field_validator("unifi_cloud_api_key")
    @classmethod
    def _blank_key_is_unset(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            return None
        return value

    @property
    def has_key(self) -> bool:
        return self.unifi_cloud_api_key is not None
