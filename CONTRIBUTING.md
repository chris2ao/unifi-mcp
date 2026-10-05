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

1. Pick the right product (`network`, `protect`, `access`) and the right module under `src/unifi_mcp/tools/<product>/`. Tool modules are auto-discovered: any module that exports a `TOOLS` list is loaded, so there is no registry to edit.
2. Declare `GROUP` in the module (Network: `core`, `security` or `insights`; Protect: `cameras` or `devices`) so loaders can register it by group.
3. For destructive operations, take a `confirm: bool = False` parameter, return `{"preview": True, ...}` when it is false, and declare the tool in the module's `TIER2_TOOLS` dict (tool name to cache category). A test fails if a tool with a `confirm` parameter is not Tier 2 (see `safety.py`).
4. Add tests under `tests/` using `respx` to mock the UniFi API. Use sanitized fixtures only (documentation IPs such as 192.0.2.x, MACs such as aa:bb:cc:00:00:01, placeholder UUIDs).
5. Regenerate the tool list with `uv run python scripts/gen_tool_docs.py` and commit `docs/TOOLS.md`. CI runs it with `--check` and fails when the file is stale. Add parameter and return details to `docs/API.md` and update the category table in `README.md`.

## OpenAPI spec workflow

The official UniFi OpenAPI specs are vendored in `docs/specs/` (Network from the console, Protect and Site Manager from developer.ui.com). After a firmware upgrade, or before adding tools for an endpoint:

```bash
uv run python scripts/spec_diff.py                # compare live specs with the vendored copies (GET only)
uv run python scripts/spec_diff.py --update       # write new vendored copies
uv run python scripts/spec_coverage.py            # which official operations have tools
```

The diff needs `UNIFI_HOST` and `UNIFI_API_KEY` for the Network spec and honors `UNIFI_VERIFY_SSL`. See `docs/SPEC_MAINTENANCE.md` for what is compared and how to act on a change.

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
