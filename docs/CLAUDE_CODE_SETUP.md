# Claude Code Setup (Manual)

Copy-paste guide for adding chris2ao-unifi-mcp to your Claude Code configuration manually. For most users, the plugin install path is simpler: see the main [README](../README.md#install-via-plugin).

## 1. Set Environment Variables

Add these to `~/.claude/secrets/secrets.env` (or `~/.zshrc` if you prefer):

```bash
export UNIFI_HOST="https://192.168.1.1"      # Your console IP
export UNIFI_API_KEY="your-api-key-here"      # From Settings > Control Plane > Integrations
```

Optional variables (with defaults):

```bash
export UNIFI_SITE="default"                   # Site name, defaults to "default"
export UNIFI_VERIFY_SSL="false"               # Set to "true" if using a valid SSL cert
```

If using `secrets.env`, make sure it is sourced in your shell profile:

```bash
# In ~/.zshrc
source ~/.claude/secrets/secrets.env
```

## 2. Add MCP Server Config

Edit `~/.claude.json` and add one of the following to the `mcpServers` section.

### Development Mode (local source)

Use this while developing or testing changes to the server:

```json
{
  "mcpServers": {
    "unifi": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/unifi-mcp", "python", "-m", "unifi_mcp"],
      "env": {}
    }
  }
}
```

Replace the `--directory` path with your local clone location.

### Published Mode (PyPI)

Use this after the package is published (Phase 4):

```json
{
  "mcpServers": {
    "unifi": {
      "command": "uvx",
      "args": ["chris2ao-unifi-mcp@latest"],
      "env": {}
    }
  }
}
```

The empty `"env": {}` block is intentional. It causes the MCP server to inherit environment variables from the launching shell, where `UNIFI_HOST` and `UNIFI_API_KEY` are already set.

## 3. Usage

Start a new Claude Code session. The server connects automatically via stdio.

### Step 1: Load tools

Tools are lazy-loaded by product. Call a loader to register the tools you need:

```
> Call load_network_tools to get started with network management.
```

This probes your console, imports 80 network tools, and registers them for use.

### Step 2: Use tools

After loading, all tools are available. Examples:

```
> List all devices on the network.
> Show me the firewall rules.
> What clients are connected right now?
> Show the network topology.
> Get the top traffic talkers.
```

### Step 3: Destructive operations (Tier 2)

For operations that modify your network, the server uses a preview-confirm pattern:

```
> Create a new VLAN called "IoT" with VLAN ID 30.
```

The tool returns a preview of what will change. To execute:

```
> Confirm the network creation.
```

### Other utility tools

These are always available without loading:

- `get_server_info`: Check server status and which products are loaded
- `get_auth_report`: View which API endpoints succeeded or failed with your API key

## Troubleshooting

**"Cannot reach UniFi console"**: Verify `UNIFI_HOST` is correct and the console is reachable from your machine.

**"API key rejected"**: Check that the API key is valid. Generate a new one from Settings > Control Plane > Integrations on your console.

**"Product not installed"**: The loader probes the console before registering tools. If you see this for Protect or Access, the product is not detected on your console.

**SSL errors**: Set `UNIFI_VERIFY_SSL=false` if your console uses a self-signed certificate (this is the default).
