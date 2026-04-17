"""Webhook / notification recipient tools.

Network 9.x replaced the dedicated `/v2/api/site/{site}/webhooks` surface with
the unified `/v2/api/site/{site}/notifications` collection. The new surface
covers webhook URLs alongside email/Discord/Slack recipients, so the legacy
"webhook" terminology is preserved here for backwards compatibility while the
underlying calls target the notifications endpoint.
"""

from unifi_mcp.auth.client import UnifiClient


def _format_notification(n: dict) -> dict:
    return {
        "id": n.get("id") or n.get("_id", ""),
        "name": n.get("name", ""),
        "url": n.get("url") or n.get("webhook_url", ""),
        "type": n.get("type", "webhook"),
        "enabled": n.get("enabled", True),
    }


async def list_webhooks(client: UnifiClient) -> list[dict]:
    """List all configured webhook / notification recipients."""
    response = await client.get(
        "/proxy/network/v2/api/site/{site}/notifications",
        cache_category="webhooks", cache_ttl=30.0,
    )
    if isinstance(response, list):
        items = response
    else:
        items = response.get("data", [])
    return [_format_notification(n) for n in items]


async def create_webhook(
    client: UnifiClient,
    name: str,
    url: str,
    enabled: bool = True,
) -> dict:
    """Create a new webhook notification recipient. Tier 1."""
    payload = {
        "name": name,
        "type": "webhook",
        "url": url,
        "enabled": enabled,
    }

    response = await client.post(
        "/proxy/network/v2/api/site/{site}/notifications",
        json=payload,
    )
    client.invalidate_cache("webhooks")
    return {"action": "create_webhook", "name": name, "response": response}


async def delete_webhook(client: UnifiClient, webhook_id: str) -> dict:
    """Delete a webhook / notification recipient. Tier 1."""
    response = await client.delete(
        f"/proxy/network/v2/api/site/{{site}}/notifications/{webhook_id}",
    )
    client.invalidate_cache("webhooks")
    return {"action": "delete_webhook", "webhook_id": webhook_id, "response": response}


TOOLS = [list_webhooks, create_webhook, delete_webhook]
