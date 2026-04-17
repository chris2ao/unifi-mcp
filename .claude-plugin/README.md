# unifi-mcp plugin

Single-file reference for what Claude Code installs when you run `/plugin install unifi-mcp@chris2ao`.

## What gets registered

One MCP server named `unifi` that speaks the Model Context Protocol over stdio.
The server process is started by `uv` from the plugin's cached repo directory
(`${CLAUDE_PLUGIN_ROOT}`), which contains the full Python package source and
`pyproject.toml`.

```
Claude Code session
    |
    v
stdio channel
    |
    v
uv run --directory <plugin-root> python -m unifi_mcp
    |
    v
FastMCP server, 5 utility tools + lazy loaders
    |
    v (on load_* call)
86 network tools / 11 protect tools
    |
    v (HTTPS with X-API-Key header)
UniFi console at UNIFI_HOST
```

## Requirements the plugin cannot install for you

- **Python 3.12+** on your `PATH`
- **uv** (`brew install uv` on macOS, `curl -LsSf https://astral.sh/uv/install.sh | sh` otherwise)
- **`UNIFI_HOST`** and **`UNIFI_API_KEY`** exported in the shell that launches
  Claude Code. See the root `README.md` for the API-key walkthrough.

The `"env": {}` block in the manifest is deliberate: it tells Claude Code
to pass the launching shell's environment through to the MCP process, so the
plugin does not need to know or store your API key.

## Verifying the install

After `/plugin install`, start a new session and run:

```
/plugin list                 # should show unifi-mcp enabled
```

Then in the session:

```
> Call get_server_info.
> Call load_network_tools.
```

`get_server_info` should return `{"server": "chris2ao-unifi-mcp", ...}`.
`load_network_tools` should register 86 tools.

## Files installed

```
${CLAUDE_PLUGIN_ROOT}/
  .claude-plugin/plugin.json      # this plugin's manifest
  .claude-plugin/marketplace.json # marketplace entry
  src/unifi_mcp/                  # Python package
  pyproject.toml                  # uv reads this when launching
  docs/                           # API reference, security review, setup
  tests/                          # not executed at runtime
```

## Upgrading

```
/plugin marketplace update chris2ao
/plugin update unifi-mcp@chris2ao
```

The cached repo is replaced in-place, so running tools mid-upgrade may be
interrupted. Prefer updating between sessions.

## Uninstalling

```
/plugin uninstall unifi-mcp@chris2ao
/plugin marketplace remove chris2ao
```

Your `UNIFI_HOST` / `UNIFI_API_KEY` environment variables are not touched; the
plugin never sets, persists, or reads them from disk.
