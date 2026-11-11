import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# One UNIFI_TOOL_GROUPS entry: "<product>:<group>", e.g. "network:core".
_TOOL_GROUP_ENTRY = re.compile(r"^(network|protect|access):([a-z][a-z0-9_]{0,39})$")


class UnifiConfig(BaseSettings):
    """UniFi MCP server configuration from environment variables."""

    unifi_host: str
    unifi_api_key: str
    unifi_site: str = "default"
    unifi_verify_ssl: bool = False
    # How long a Tier 2 preview stays valid for the matching confirm=True call.
    unifi_preview_ttl_seconds: int = Field(default=600, ge=1, le=86400)
    # Default tool groups for the product loaders, comma separated, for example
    # "network:core,network:security,protect:cameras". Unset loads every group.
    # A product that is not mentioned loads all of its groups.
    unifi_tool_groups: str | None = None
    # Groups registered at startup, same format, for clients that cannot call the
    # loaders (for example an agent whose tool allowlist excludes them). Registered
    # without probing the console; unset preloads nothing.
    unifi_preload_groups: str | None = None

    model_config = {"env_prefix": "", "case_sensitive": False}

    @field_validator("unifi_tool_groups", "unifi_preload_groups", mode="before")
    @classmethod
    def _normalize_tool_groups(cls, value: object, info) -> str | None:
        """Lowercase, trim and de-duplicate entries; reject anything not product:group."""
        variable = info.field_name.upper()
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{variable} must be a comma-separated string")
        entries = [entry.strip().lower() for entry in value.split(",") if entry.strip()]
        if not entries:
            return None
        invalid = [entry for entry in entries if not _TOOL_GROUP_ENTRY.match(entry)]
        if invalid:
            raise ValueError(
                f"{variable} entries must look like 'network:core' (product "
                f"network, protect or access); invalid: {', '.join(invalid)}"
            )
        return ",".join(dict.fromkeys(entries))

    def preload_groups(self) -> dict[str, list[str]]:
        """Groups UNIFI_PRELOAD_GROUPS registers at startup, by product."""
        groups: dict[str, list[str]] = {}
        for entry in (self.unifi_preload_groups or "").split(","):
            if entry:
                product, group = entry.split(":", 1)
                groups.setdefault(product, []).append(group)
        return groups

    def tool_groups_for(self, product: str) -> list[str] | None:
        """Groups UNIFI_TOOL_GROUPS selects for a product, or None to load all of them."""
        if not self.unifi_tool_groups:
            return None
        groups = [
            group
            for entry in self.unifi_tool_groups.split(",")
            for prefix, group in [entry.split(":", 1)]
            if prefix == product
        ]
        return groups or None
