from pydantic_settings import BaseSettings


class UnifiConfig(BaseSettings):
    """UniFi MCP server configuration from environment variables."""

    unifi_host: str
    unifi_api_key: str
    unifi_site: str = "default"
    unifi_verify_ssl: bool = False

    model_config = {"env_prefix": "", "case_sensitive": False}
