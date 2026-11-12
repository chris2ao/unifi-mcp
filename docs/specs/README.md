# Vendored OpenAPI specs

Snapshots of the official UniFi Integration API specs that unifi-mcp targets. They are the reference for exact request bodies, enums and response shapes, and the baseline that `scripts/spec_diff.py` compares against.

| File | Service | Source |
|------|---------|--------|
| `network-11.0.99.json` | Network Integration API | Console: `GET /proxy/network/api-docs/integration.json` on Network 11.0.99 (same operations as `https://developer.ui.com/network/v11.0.97/openapi.json`) |
| `protect-7.3.70.json` | Protect Integration API | `https://developer.ui.com/protect/v7.3.70/openapi.json` (kept to match the installed Protect 7.3 line; 7.4.96 is published, see `docs/COMPATIBILITY.md`) |
| `site-manager-1.0.0.json` | Site Manager (cloud) API | `https://developer.ui.com/site-manager/v1.0.0/openapi.json` |

Sources:

- The console serves its own Network spec at `GET /proxy/network/api-docs/integration.json` (X-API-Key header). It always matches the running firmware.
- Ubiquiti publishes every product spec at `https://developer.ui.com/{service}/v{version}/openapi.json`. The index with current versions is `https://developer.ui.com/llms.txt`.

Files are pretty-printed with sorted keys (indent 2) so diffs in git stay small and stable. File names are `{service}-{version}.json`. Do not edit them by hand: refresh with `uv run python scripts/spec_diff.py --update`. See `docs/SPEC_MAINTENANCE.md`.
