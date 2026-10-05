"""Webhook / notification recipient tools (currently unavailable).

Network 9.x moved webhook recipients from `/v2/api/site/{site}/webhooks` to
`/v2/api/site/{site}/notifications`. On Network 10.6.106 that path also returns
404, and no replacement was found among ten candidate paths. The tools are kept
so existing callers get a clear PRODUCT_UNAVAILABLE explanation instead of a
missing-tool error. Configure webhook recipients in the Network web UI.
"""

from unifi_mcp.auth.client import UnifiClient

TIER2_TOOLS: dict[str, str] = {
    "create_webhook": "webhooks",
    "delete_webhook": "webhooks",
}

_WEBHOOKS_UNAVAILABLE = {
    "error": True,
    "category": "PRODUCT_UNAVAILABLE",
    "message": (
        "Webhook recipient management is not available through the Network API "
        "(verified on Network 10.6.106): /v2/api/site/{site}/webhooks and "
        "/v2/api/site/{site}/notifications both return 404. Manage webhook "
        "recipients in the UniFi Network web UI."
    ),
}


async def list_webhooks(client: UnifiClient) -> dict:
    """List webhook recipients. Currently unavailable via the API."""
    return dict(_WEBHOOKS_UNAVAILABLE)


async def create_webhook(
    client: UnifiClient, name: str, url: str, confirm: bool = False,
) -> dict:
    """Create a webhook recipient. Currently unavailable via the API."""
    return dict(_WEBHOOKS_UNAVAILABLE)


async def delete_webhook(
    client: UnifiClient, webhook_id: str, confirm: bool = False,
) -> dict:
    """Delete a webhook recipient. Currently unavailable via the API."""
    return dict(_WEBHOOKS_UNAVAILABLE)


create_webhook.never_previews = True  # stub: no preview is ever produced, see server._run_guarded
delete_webhook.never_previews = True  # stub: no preview is ever produced, see server._run_guarded

TOOLS = [list_webhooks, create_webhook, delete_webhook]
