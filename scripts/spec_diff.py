#!/usr/bin/env python3
"""Diff the live UniFi OpenAPI specs against the vendored copies in docs/specs/.

Network spec: fetched from the console (GET /proxy/network/api-docs/integration.json,
UNIFI_HOST + UNIFI_API_KEY). TLS verification follows UNIFI_VERIFY_SSL like the
server (default off). The API key is never sent over plain http and the request
refuses to follow redirects, so the key cannot be forwarded to another host.
Protect and Site Manager specs: fetched from developer.ui.com (versions parsed from
https://developer.ui.com/llms.txt).

Only GET requests are ever made. Standard library only.

Usage:
    python scripts/spec_diff.py                  # markdown report
    python scripts/spec_diff.py --json           # JSON report
    python scripts/spec_diff.py --update         # also write new vendored copies
    python scripts/spec_diff.py --offline A B    # diff two local spec files
    python scripts/spec_diff.py --fail-on-change # exit 1 when anything changed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = REPO_ROOT / "docs" / "specs"
LLMS_URL = "https://developer.ui.com/llms.txt"
SPEC_URL = "https://developer.ui.com/{service}/v{version}/openapi.json"
CONSOLE_SPEC_PATH = "/proxy/network/api-docs/integration.json"
SERVICES = ("network", "protect", "site-manager")
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
MAX_DEPTH = 5
TIMEOUT = 30
VERSION_RE = re.compile(r"^\d[0-9A-Za-z.\-]*$")


# ---------------------------------------------------------------- fetching


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so credential headers never reach another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def _http_get(
    url: str,
    headers: dict[str, str] | None = None,
    verify: bool = True,
    follow_redirects: bool = True,
) -> bytes:
    """GET a URL and return the body. Raises RuntimeError with a clean message."""
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    context = None
    if not verify:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        if follow_redirects:
            with urllib.request.urlopen(request, timeout=TIMEOUT, context=context) as resp:
                return resp.read()
        opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPSHandler(context=context)
        )
        with opener.open(request, timeout=TIMEOUT) as resp:
            return resp.read()
    except Exception as exc:  # urllib raises many types; never leak headers
        raise RuntimeError(f"GET {url} failed: {type(exc).__name__}: {exc}") from exc


def _normalize_host(host: str) -> str:
    host = host.strip().rstrip("/")
    return host if re.match(r"^https?://", host) else f"https://{host}"


def env_verify_ssl(environ: dict[str, str] | None = None) -> bool:
    """Read UNIFI_VERIFY_SSL the way the server does (default False)."""
    raw = (environ if environ is not None else os.environ).get("UNIFI_VERIFY_SSL", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def fetch_console_network_spec(host: str, api_key: str, verify: bool = False) -> dict:
    """Fetch the Network integration spec from the console.

    Refuses plain http (the key would travel in cleartext) and never follows redirects.
    """
    base = _normalize_host(host)
    if not base.lower().startswith("https://"):
        raise RuntimeError("UNIFI_HOST must use https:// because the API key is sent with the request")
    body = _http_get(
        base + CONSOLE_SPEC_PATH,
        headers={"X-API-Key": api_key, "Accept": "application/json"},
        verify=verify,
        follow_redirects=False,
    )
    return json.loads(body)


def parse_llms_versions(text: str) -> dict[str, str]:
    """Extract {service: version} from the llms.txt OpenAPI Specifications list."""
    found: dict[str, str] = {}
    pattern = r"https://developer\.ui\.com/([a-z0-9-]+)/v?([0-9][0-9A-Za-z.\-]*)/openapi\.json"
    for service, version in re.findall(pattern, text):
        found.setdefault(service, version)
    return found


def fetch_published_spec(service: str, version: str) -> dict:
    """Fetch a published spec from developer.ui.com."""
    body = _http_get(SPEC_URL.format(service=service, version=version))
    return json.loads(body)


# ---------------------------------------------------------------- vendored


def _version_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", version))


def find_vendored(service: str, spec_dir: Path = SPEC_DIR) -> tuple[str, Path] | None:
    """Return (version, path) of the newest vendored spec for a service."""
    pattern = re.compile(rf"^{re.escape(service)}-(\d[0-9A-Za-z.\-]*)\.json$")
    candidates = []
    for path in spec_dir.glob(f"{service}-*.json"):
        match = pattern.match(path.name)
        if match:
            candidates.append((_version_key(match.group(1)), match.group(1), path))
    if not candidates:
        return None
    _, version, path = max(candidates)
    return version, path


def load_spec(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_spec(spec: dict) -> str:
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_vendored(service: str, version: str, spec: dict, spec_dir: Path = SPEC_DIR) -> Path:
    """Write a vendored copy and remove older versions of the same service."""
    spec_dir.mkdir(parents=True, exist_ok=True)
    target = spec_dir / f"{service}-{version}.json"
    target.write_text(dump_spec(spec), encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(service)}-\d[0-9A-Za-z.\-]*\.json$")
    for old in spec_dir.glob(f"{service}-*.json"):
        if old != target and pattern.match(old.name):
            old.unlink()
    return target


# ---------------------------------------------------------------- analysis


def resolve_ref(spec: dict, ref: str) -> dict:
    node: Any = spec
    for part in ref.lstrip("#/").split("/"):
        node = node.get(part.replace("~1", "/").replace("~0", "~"), {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def _merge_props(into: dict[str, dict], more: dict[str, dict]) -> None:
    for key, value in more.items():
        into.setdefault(key, value)


_CONSTRAINT_KEYS = ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "format")


def _constraints(schema: dict) -> str:
    """Compact, stable label for the numeric and length limits of a schema."""
    if not isinstance(schema, dict):
        return ""
    return ",".join(f"{k}={schema[k]}" for k in _CONSTRAINT_KEYS if k in schema)


def _discriminator_props(spec: dict, schema: dict, prefix: str, depth: int, seen: tuple) -> dict[str, dict]:
    """Flatten the subtypes of a polymorphic schema under `[KEY]` prefixes.

    The base schema lists `discriminator.mapping` to its subtypes. Each subtype is
    flattened under `<prefix>[KEY]` and the mapping keys become enum values of the
    discriminator property, so a new or removed variant shows up as an enum change.
    """
    disc = schema.get("discriminator")
    mapping = disc.get("mapping") if isinstance(disc, dict) else None
    if not isinstance(mapping, dict) or not mapping:
        return {}
    out: dict[str, dict] = {}
    name = disc.get("propertyName")
    if name:
        path = f"{prefix}.{name}" if prefix else name
        out[path] = {
            "type": "string",
            "enum": sorted(map(str, mapping)),
            "required": True,
            "limits": "",
        }
    for key, target in mapping.items():
        if not isinstance(target, str) or target in seen:
            continue
        variant = f"{prefix}[{key}]"
        for sub_path, sub_value in flatten_schema(
            spec, {"$ref": target}, variant, depth + 1, seen
        ).items():
            out.setdefault(sub_path, sub_value)
    return out


def flatten_schema(spec: dict, schema: dict, prefix: str = "", depth: int = 0, seen: tuple = ()) -> dict[str, dict]:
    """Flatten a schema into {dotted.property: {type, enum, required}}."""
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return {}
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in seen:
            return {}
        return flatten_schema(spec, resolve_ref(spec, ref), prefix, depth, seen + (ref,))

    out: dict[str, dict] = {}
    for key in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(key, []) or []:
            _merge_props(out, flatten_schema(spec, sub, prefix, depth, seen))

    required = set(schema.get("required", []) or [])
    for name, sub in (schema.get("properties") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        resolved = sub
        sub_seen = seen
        if isinstance(sub, dict) and "$ref" in sub:
            if sub["$ref"] in seen:
                continue
            resolved = resolve_ref(spec, sub["$ref"])
            sub_seen = seen + (sub["$ref"],)
        out[path] = {
            "type": _type_label(resolved),
            "enum": sorted(map(str, resolved.get("enum", []) or [])),
            "required": name in required,
            "limits": _constraints(resolved),
        }
        _merge_props(out, flatten_schema(spec, resolved, path, depth + 1, sub_seen))
        items = resolved.get("items") if isinstance(resolved, dict) else None
        if isinstance(items, dict):
            item_prefix = f"{path}[]"
            resolved_items = items
            item_seen = sub_seen
            if "$ref" in items:
                if items["$ref"] in sub_seen:
                    continue
                resolved_items = resolve_ref(spec, items["$ref"])
                item_seen = sub_seen + (items["$ref"],)
            if resolved_items.get("enum"):
                out[item_prefix] = {
                    "type": _type_label(resolved_items),
                    "enum": sorted(map(str, resolved_items["enum"])),
                    "required": False,
                    "limits": _constraints(resolved_items),
                }
            _merge_props(out, flatten_schema(spec, resolved_items, item_prefix, depth + 1, item_seen))

    for key, value in _discriminator_props(spec, schema, prefix, depth, seen).items():
        if key in out and key.rpartition(".")[2] == (schema.get("discriminator") or {}).get("propertyName"):
            merged = sorted(set(out[key]["enum"]) | set(value["enum"]))
            out[key] = {**out[key], "enum": merged}
        else:
            out.setdefault(key, value)
    return out


def _type_label(schema: dict) -> str:
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = "|".join(map(str, kind))
    if kind == "array":
        items = schema.get("items") or {}
        inner = items.get("type") if isinstance(items, dict) else None
        return f"array<{inner or 'object'}>"
    if kind:
        return str(kind)
    if schema.get("properties"):
        return "object"
    return "any"


def body_schema(spec: dict, operation: dict) -> dict:
    request_body = operation.get("requestBody") or {}
    if "$ref" in request_body:
        request_body = resolve_ref(spec, request_body["$ref"])
    content = request_body.get("content") or {}
    media = content.get("application/json") or next(iter(content.values()), {})
    return media.get("schema") or {}


def response_schema(spec: dict, operation: dict) -> dict[str, dict]:
    """Flatten the JSON schemas of every 2xx response of an operation."""
    flat: dict[str, dict] = {}
    for code, response in (operation.get("responses") or {}).items():
        if not str(code).startswith("2") or not isinstance(response, dict):
            continue
        if "$ref" in response:
            response = resolve_ref(spec, response["$ref"])
        content = response.get("content") or {}
        media = content.get("application/json") or next(iter(content.values()), {})
        _merge_props(flat, flatten_schema(spec, (media or {}).get("schema") or {}))
    return flat


def extract_operations(spec: dict) -> dict[str, dict]:
    """Return {"METHOD /path": {"body": {...}, "params": {...}}} for every operation."""
    operations: dict[str, dict] = {}
    for path, item in (spec.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method in HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            params: dict[str, dict] = {}
            for raw in list(shared) + list(op.get("parameters") or []):
                param = resolve_ref(spec, raw["$ref"]) if "$ref" in raw else raw
                if not param.get("name"):
                    continue
                schema = param.get("schema") or {}
                params[f"{param.get('in', '?')}:{param['name']}"] = {
                    "type": _type_label(schema),
                    "enum": sorted(map(str, schema.get("enum", []) or [])),
                    "required": bool(param.get("required")),
                    "limits": _constraints(schema),
                }
            operations[f"{method.upper()} {path}"] = {
                "body": flatten_schema(spec, body_schema(spec, op)),
                "response": response_schema(spec, op),
                "params": params,
            }
    return operations


# ---------------------------------------------------------------- diffing


def _diff_props(label: str, old: dict[str, dict], new: dict[str, dict]) -> list[str]:
    changes: list[str] = []
    for name in sorted(new.keys() - old.keys()):
        extra = f" enum [{', '.join(new[name]['enum'])}]" if new[name]["enum"] else ""
        req = ", required" if new[name]["required"] else ""
        changes.append(f"{label} added `{name}` ({new[name]['type']}{req}){extra}")
    for name in sorted(old.keys() - new.keys()):
        changes.append(f"{label} removed `{name}`")
    for name in sorted(old.keys() & new.keys()):
        before, after = old[name], new[name]
        if before["type"] != after["type"]:
            changes.append(f"{label} `{name}` type {before['type']} -> {after['type']}")
        if before["required"] != after["required"]:
            state = "now required" if after["required"] else "no longer required"
            changes.append(f"{label} `{name}` {state}")
        if before.get("limits", "") != after.get("limits", ""):
            changes.append(
                f"{label} `{name}` limits {before.get('limits') or 'none'} -> {after.get('limits') or 'none'}"
            )
        added = sorted(set(after["enum"]) - set(before["enum"]))
        removed = sorted(set(before["enum"]) - set(after["enum"]))
        if added:
            changes.append(f"{label} `{name}` enum added: {', '.join(added)}")
        if removed:
            changes.append(f"{label} `{name}` enum removed: {', '.join(removed)}")
    return changes


def diff_specs(old_spec: dict, new_spec: dict) -> dict:
    """Diff two specs. Returns operations added/removed/changed plus version info."""
    old_ops = extract_operations(old_spec)
    new_ops = extract_operations(new_spec)
    changed = []
    for key in sorted(old_ops.keys() & new_ops.keys()):
        changes = _diff_props("body", old_ops[key]["body"], new_ops[key]["body"])
        changes += _diff_props("response", old_ops[key]["response"], new_ops[key]["response"])
        changes += _diff_props("param", old_ops[key]["params"], new_ops[key]["params"])
        if changes:
            changed.append({"operation": key, "changes": changes})
    return {
        "old_version": (old_spec.get("info") or {}).get("version"),
        "new_version": (new_spec.get("info") or {}).get("version"),
        "added_operations": sorted(new_ops.keys() - old_ops.keys()),
        "removed_operations": sorted(old_ops.keys() - new_ops.keys()),
        "changed_operations": changed,
    }


def has_changes(result: dict) -> bool:
    return bool(
        result.get("version_changed")
        or result.get("added_operations")
        or result.get("removed_operations")
        or result.get("changed_operations")
    )


def build_result(service: str, old_version: str, new_version: str, old_spec: dict, new_spec: dict) -> dict:
    diff = diff_specs(old_spec, new_spec)
    diff.update(
        {
            "service": service,
            "vendored_version": old_version,
            "current_version": new_version,
            "version_changed": old_version != new_version,
            "error": None,
        }
    )
    return diff


def error_result(service: str, message: str) -> dict:
    return {
        "service": service,
        "error": message,
        "version_changed": False,
        "added_operations": [],
        "removed_operations": [],
        "changed_operations": [],
    }


# ---------------------------------------------------------------- orchestration


def collect_online(
    spec_dir: Path = SPEC_DIR,
    host: str | None = None,
    api_key: str | None = None,
    verify: bool = False,
) -> tuple[list[dict], dict[str, tuple[str, dict]]]:
    """Fetch current specs and diff them. Returns (results, {service: (version, spec)})."""
    results: list[dict] = []
    fetched: dict[str, tuple[str, dict]] = {}

    try:
        versions = parse_llms_versions(_http_get(LLMS_URL).decode("utf-8", "replace"))
    except RuntimeError as exc:
        versions = {}
        llms_error = str(exc)
    else:
        llms_error = None

    for service in SERVICES:
        vendored = find_vendored(service, spec_dir)
        try:
            if service == "network":
                if not host or not api_key:
                    raise RuntimeError("UNIFI_HOST and UNIFI_API_KEY must be set to fetch the Network spec")
                spec = fetch_console_network_spec(host, api_key, verify)
                version = str((spec.get("info") or {}).get("version") or "")
                if not VERSION_RE.match(version):
                    raise RuntimeError(f"console reported an unusable spec version: {version!r}")
            else:
                if service not in versions:
                    raise RuntimeError(llms_error or f"{service} not listed in llms.txt")
                version = versions[service]
                spec = fetch_published_spec(service, version)
        except (RuntimeError, ValueError) as exc:
            results.append(error_result(service, str(exc)))
            continue
        fetched[service] = (version, spec)
        if vendored is None:
            results.append(error_result(service, "no vendored spec found; run with --update"))
            continue
        old_version, old_path = vendored
        results.append(build_result(service, old_version, version, load_spec(old_path), spec))
    return results, fetched


def collect_offline(path_a: Path, path_b: Path) -> list[dict]:
    old_spec, new_spec = load_spec(path_a), load_spec(path_b)
    title = (new_spec.get("info") or {}).get("title") or path_b.stem
    old_v = (old_spec.get("info") or {}).get("version") or path_a.stem
    new_v = (new_spec.get("info") or {}).get("version") or path_b.stem
    return [build_result(title, str(old_v), str(new_v), old_spec, new_spec)]


# ---------------------------------------------------------------- output


def render_markdown(results: list[dict]) -> str:
    lines = ["# OpenAPI spec diff", ""]
    for result in results:
        lines.append(f"## {result['service']}")
        if result.get("error"):
            lines += [f"- ERROR: {result['error']}", ""]
            continue
        lines.append(f"- Vendored version: {result['vendored_version']}")
        lines.append(f"- Current version: {result['current_version']}")
        if not has_changes(result):
            lines += ["- No changes.", ""]
            continue
        if result["version_changed"]:
            lines.append("- Version changed: yes")
        for title, key in (("Added operations", "added_operations"), ("Removed operations", "removed_operations")):
            if result[key]:
                lines += ["", f"### {title} ({len(result[key])})"]
                lines += [f"- `{op}`" for op in result[key]]
        if result["changed_operations"]:
            lines += ["", f"### Changed operations ({len(result['changed_operations'])})"]
            for entry in result["changed_operations"]:
                lines.append(f"- `{entry['operation']}`")
                lines += [f"  - {change}" for change in entry["changes"]]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diff UniFi OpenAPI specs against vendored copies.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    parser.add_argument("--update", action="store_true", help="write new vendored copies to docs/specs/")
    parser.add_argument("--offline", nargs=2, metavar=("A", "B"), help="diff two local spec files")
    parser.add_argument("--fail-on-change", action="store_true", help="exit 1 on any change or fetch error")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    updated: list[str] = []
    if args.offline:
        results = collect_offline(Path(args.offline[0]), Path(args.offline[1]))
    else:
        results, fetched = collect_online(
            SPEC_DIR,
            os.environ.get("UNIFI_HOST"),
            os.environ.get("UNIFI_API_KEY"),
            env_verify_ssl(),
        )
        if args.update:
            for service, (version, spec) in fetched.items():
                path = write_vendored(service, version, spec, SPEC_DIR)
                updated.append(str(path.relative_to(REPO_ROOT)))

    if args.json:
        print(json.dumps({"results": results, "updated_files": updated}, indent=2, sort_keys=True))
    else:
        print(render_markdown(results), end="")
        if updated:
            print("\nUpdated vendored specs:\n" + "\n".join(f"- {name}" for name in updated))

    if args.fail_on_change and any(r.get("error") or has_changes(r) for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
