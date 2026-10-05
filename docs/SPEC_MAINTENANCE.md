# OpenAPI spec maintenance

unifi-mcp targets Ubiquiti's official Integration APIs. The specs are vendored in `docs/specs/` (see `docs/specs/README.md`) and two stdlib-only scripts keep them honest. Run them with `uv run python scripts/<name>.py`.

## After every firmware upgrade

```
export UNIFI_HOST=https://<console>
export UNIFI_API_KEY=<key>
uv run python scripts/spec_diff.py
```

This makes GET requests only: the Network spec from the console (`/proxy/network/api-docs/integration.json`). TLS verification follows `UNIFI_VERIFY_SSL` like the server (default off). The script refuses a plain `http://` host, because the API key is sent with the request, and refuses to follow redirects, so the key can never be forwarded to another host and the latest Protect and Site Manager specs from developer.ui.com (versions parsed from `llms.txt`). Each is diffed against the newest vendored copy.

## Reading the output

Per service you get the vendored and current versions, then:

- **Added operations**: new `METHOD /path` endpoints. Candidates for new tools.
- **Removed operations**: endpoints that disappeared. Check whether a tool still calls them and add a `PRODUCT_UNAVAILABLE` stub if so.
- **Changed operations**: per operation, what changed in these parts of the contract. Review enums and validation in the matching tool module.

What is compared:

- Request body properties: added, removed, type, required, enum values, and limits (`minimum`, `maximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, `format`).
- Polymorphic request bodies: the subtypes listed in `discriminator.mapping` are flattened under `[KEY]` prefixes (for example `[A_RECORD].ipv4Address`), and a new or removed variant is reported as an enum change on the discriminator property (for example `type`).
- 2xx response schemas, reported with a `response` label, so a renamed or removed response field is visible. The read tools depend on those shapes.
- Query, path and header parameters: added, removed, type, required, enum and limits.

What is not compared: descriptions and examples, non-2xx responses, security schemes, tags, and nesting deeper than five levels. Compare those by hand with `--offline` if a change matters.

A fetch failure is reported as `ERROR` for that service and does not stop the others. Use `--json` for machine-readable output. Exit code is 0 unless `--fail-on-change` is given, in which case any change or error exits 1 (useful in CI or a cron check).

To compare two local files (for example two vendored versions): `uv run python scripts/spec_diff.py --offline docs/specs/protect-7.3.70.json /path/to/new.json`.

## Updating the vendored specs

After reviewing a diff, run `uv run python scripts/spec_diff.py --update`. A console version that is not a plain version string (digits, letters, dots and dashes, starting with a digit) is rejected before it can become a file name. It writes `docs/specs/{service}-{version}.json` (pretty-printed, sorted keys) and removes the superseded version file. Then update the version list in `docs/specs/README.md` and commit the new files together with any tool changes they motivated.

## Coverage

```
uv run python scripts/spec_coverage.py
uv run python scripts/spec_coverage.py --check-min 60
```

Lists every operation in each vendored spec and whether any string literal under `src/unifi_mcp/tools` references its path. Top-level string constants such as `_BASE = "/proxy/network/integration/..."` are substituted into f-strings and `+` concatenations, so paths built from a module constant are found. Path params are normalized (`{siteId}`, `{site_id}` and `{id}` all match), query strings are ignored, and the `/proxy/network/integration` and `/proxy/protect/integration` prefixes are stripped. Matching is by path only, not HTTP method, so a covered path may still lack some of its methods. The report ends each section with a percentage; `--check-min N` exits 1 if any spec is below N percent.

## Tool documentation

`docs/TOOLS.md` is generated from the tool modules. After adding or changing tools run `uv run python scripts/gen_tool_docs.py`; CI runs it with `--check`. The script includes only modules tracked or staged in git and refuses to run (exit 2) when a tracked tool module has unstaged edits, because those edits could belong to a later release. Stage the edits, or generate from a clean checkout (`git worktree add`).
