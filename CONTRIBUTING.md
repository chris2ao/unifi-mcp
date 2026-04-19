# Contributing to unifi-mcp

Thanks for the interest. This project welcomes bug reports, new tools for UniFi Network/Protect/Access, and documentation improvements.

## Scope

This server wraps UniFi Network, Protect, and (optionally) Access APIs as MCP tools, with lazy product loading and a preview-confirm safety model for destructive operations. In scope:

- Adding tools that map to UniFi REST endpoints
- Expanding Protect or Access coverage
- Improving the preview-confirm safety model
- Auth discovery and error-handling hardening
- Documentation, examples, and the capability matrix

Out of scope:

- Cloud UniFi Site Manager API (local-console only)
- Non-MCP transports (HTTP, SSE are not planned here)

## Development setup

```bash
git clone https://github.com/chris2ao/unifi-mcp.git
cd unifi-mcp
uv sync --extra dev
uv run pytest -q
```

CI runs on Python 3.12 and 3.13. Tests must pass before a PR is considered.

## Running against a real UniFi console

Set `UNIFI_HOST` and `UNIFI_API_KEY`. The key is a **local-console API key** (UDM / UniFi OS → Settings → Control Plane → Integrations), not a cloud Site Manager key.

```bash
export UNIFI_HOST=https://<udm-ip>
export UNIFI_API_KEY=<local-console-key>
uv run python -m unifi_mcp
```

## Adding a tool

1. Pick the right product (`network`, `protect`, `access`) and the right module under `src/unifi_mcp/tools/<product>/`.
2. Define the tool function, decorated via the product registry pattern.
3. For destructive operations, follow the preview-confirm safety model (see `safety.py`).
4. Update the tool inventory in `README.md` and the capability matrix in `docs/`.
5. Add tests under `tests/` using `respx` to mock the UniFi API.

## Pull request process

1. Branch from `main`.
2. Keep PRs focused. One feature or fix per PR.
3. Update tests and docs alongside the code change.
4. CI must pass before review.
5. Squash-and-merge is the default merge strategy.

## Commit messages

Conventional Commits format: `<type>: <description>` where type is one of `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

## Reporting issues

Use the issue templates in `.github/ISSUE_TEMPLATE/`:

- **Bug report** for broken behavior
- **Feature request** for new capability
- **Missing tool** for a specific UniFi endpoint that isn't wrapped yet

## Code of conduct

This project follows the [Contributor Covenant](./CODE_OF_CONDUCT.md). Be respectful.
