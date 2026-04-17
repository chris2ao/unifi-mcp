"""Backup management tools: list, create, restore.

Uses V1 cmd API per the endpoint catalog:
/proxy/network/api/s/{site}/cmd/backup
"""

from unifi_mcp.auth.client import UnifiClient


async def list_backups(client: UnifiClient) -> list[dict]:
    """List all available controller backups."""
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/backup",
        json={"cmd": "list-backups"},
    )
    return [
        {
            "filename": b.get("filename", ""),
            "time": b.get("time", 0),
            "size": b.get("size", 0),
        }
        for b in response.get("data", [])
    ]


async def create_backup(client: UnifiClient) -> dict:
    """Create a new controller backup. Tier 1 (non-destructive read/export)."""
    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/backup",
        json={"cmd": "backup"},
    )
    return {"action": "create_backup", "response": response}


async def restore_backup(client: UnifiClient, filename: str, confirm: bool = False) -> dict:
    """Restore a controller backup. Requires confirm=True after previewing.

    WARNING: This will restart the controller and replace all settings.
    """
    if not confirm:
        return {
            "preview": True,
            "action": "restore_backup",
            "filename": filename,
            "message": f"Will restore backup '{filename}'. This replaces ALL settings and restarts the controller. Call again with confirm=True to execute.",
        }

    response = await client.post(
        "/proxy/network/api/s/{site}/cmd/backup",
        json={"cmd": "restore", "filename": filename},
    )
    client.invalidate_cache("backups")
    return {"executed": True, "action": "restore_backup", "filename": filename, "response": response}


TOOLS = [list_backups, create_backup, restore_backup]
