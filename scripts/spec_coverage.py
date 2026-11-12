#!/usr/bin/env python3
"""Report which vendored OpenAPI operations unifi-mcp calls, by HTTP method and path.

An operation counts as covered when the source calls its normalized path with
its HTTP method. The scan reads src/unifi_mcp/tools plus src/unifi_mcp/server.py
and resolves, per module:

- calls on a client object (`client.get`, `get_all_pages`, `get_binary`, `post`,
  `put`, `patch`, `delete`): the receiver name must contain "client", so
  `dict.get` is never mistaken for a request;
- the path argument as a literal, an f-string, a `+` concatenation, a module
  constant (`_BASE = "/proxy/..."`, substituted into f-strings), or a local
  variable assigned one of those;
- paths handed to a local helper that makes the call (the helper's methods are
  used), and paths built by a local helper the caller passes on (the caller's
  methods are used). Such indirect paths take every method their functions use,
  so they can overcount when one function calls one path with several methods;
- constants imported from another scanned module (`from unifi_mcp.tools.network.zbf_official
  import _BASE`), and module-level dicts, lists or tuples of paths that a
  function reads (for example a product-to-endpoint map);
- templated segments: `{kind}` is expanded from a module constant named `KINDS`
  (or `KIND`), so routes such as `/v1/{kind}/{id}` count per accessory type.
  Tuples, lists and sets of strings expand to their values, dicts to their keys
  and the keys of dict values. Candidates the spec does not list are ignored.

Path params are normalized (`{siteId}`, `{site_id}` and `{id}` all match),
query strings are ignored, and the integration prefixes are stripped. The
report also gives the path-only percentage for comparison with older reports.
Standard library only.

Usage:
    python scripts/spec_coverage.py
    python scripts/spec_coverage.py --check-min 60
"""

from __future__ import annotations

import argparse
import ast
import itertools
import re
import sys
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_diff  # noqa: E402

REPO_ROOT = spec_diff.REPO_ROOT
TOOLS_DIR = REPO_ROOT / "src" / "unifi_mcp" / "tools"
EXTRA_FILES = (REPO_ROOT / "src" / "unifi_mcp" / "server.py",)
PREFIXES = {
    "network": "/proxy/network/integration",
    "protect": "/proxy/protect/integration",
    "site-manager": "",
}
CLIENT_METHODS = {
    "get": "GET", "get_all_pages": "GET", "get_binary": "GET", "get_paginated": "GET",
    "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE",
}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_EXPANSIONS = 256

Ref = tuple[str, str]  # (HTTP method, raw path)


def normalize_path(path: str, prefix: str = "") -> str:
    """Normalize a path: strip query/prefix, collapse every {param} to {}."""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    path = re.sub(r"\{\{[^{}]*\}\}|\{[^{}]*\}", "{}", path)
    return path.rstrip("/") or "/"


def _literal(node: ast.AST, consts: dict[str, str] | None = None) -> str | None:
    """Best-effort string value of a node. Module constants in `consts` are substituted.

    An f-string placeholder that is a bare name keeps the name (`{kind}`), so
    it can be expanded later; any other expression becomes `{}`.
    """
    consts = consts or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return consts.get(node.id)
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                name = value.value.id
                parts.append(consts[name] if name in consts else "{" + name + "}")
            else:
                parts.append("{}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal(node.left, consts)
        right = _literal(node.right, consts)
        if left is None and right is None:
            return None
        return (left if left is not None else "{}") + (right if right is not None else "{}")
    return None


_URL_PREFIX = re.compile(r"^[^/]*://[^/]*")


def _path_of(text: str | None) -> str | None:
    """The path of a literal: itself when it starts with "/", the path part of a URL template."""
    if text and "://" in text:
        text = _URL_PREFIX.sub("", text)
    return text if text and text.startswith("/") and len(text) > 1 else None


def _is_path(text: str | None) -> bool:
    return _path_of(text) is not None


def _module_assigns(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out.append((node.targets[0].id, node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            out.append((node.target.id, node.value))
    return out


def module_constants(tree: ast.Module, seed: dict[str, str] | None = None) -> dict[str, str]:
    """Collect top-level `NAME = "..."` style assignments, resolving references between them.

    `seed` holds constants imported from other modules; local assignments win.
    """
    consts: dict[str, str] = dict(seed or {})
    assigns = _module_assigns(tree)
    for _ in range(3):  # a few passes resolve constants built from earlier constants
        for name, value_node in assigns:
            value = _literal(value_node, consts)
            if value is not None:
                consts[name] = value
    return consts


def module_sequences(tree: ast.Module) -> dict[str, list[str]]:
    """Top-level string collections usable to expand `{name}` placeholders."""
    seqs: dict[str, list[str]] = {}
    for name, node in _module_assigns(tree):
        try:
            value = ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(value, (tuple, list, set, frozenset)) and value and all(isinstance(v, str) for v in value):
            seqs[name] = sorted(value)
        elif isinstance(value, dict) and value and all(isinstance(k, str) for k in value):
            keys = set(value)
            for inner in value.values():
                if isinstance(inner, dict):
                    keys |= {k for k in inner if isinstance(k, str)}
            seqs[name] = sorted(keys)
    return seqs


def module_path_collections(tree: ast.Module, consts: dict[str, str]) -> dict[str, list[str]]:
    """Top-level dicts, lists, tuples and sets that hold URL paths, by name."""
    out: dict[str, list[str]] = {}
    for name, node in _module_assigns(tree):
        if not isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
            continue
        paths = sorted({t for child in ast.walk(node) if (t := _path_of(_literal(child, consts)))})
        if paths:
            out[name] = paths
    return out


def expand_placeholders(path: str, seqs: dict[str, list[str]]) -> list[str]:
    """Expand `{name}` placeholders that have a NAMES / NAME collection in the module."""
    names = [m for m in dict.fromkeys(_PLACEHOLDER.findall(path))
             if (m.upper() + "S") in seqs or m.upper() in seqs]
    if not names:
        return [path]
    choices = [seqs.get(n.upper() + "S") or seqs[n.upper()] for n in names]
    out = [path]  # the template itself still matches a real {param} segment
    for combo in itertools.islice(itertools.product(*choices), _MAX_EXPANSIONS):
        text = path
        for name, value in zip(names, combo):
            text = text.replace("{" + name + "}", value)
        out.append(text)
    return out


def _client_method(node: ast.AST) -> str | None:
    """HTTP method of a `<...client...>.<method>(...)` call, else None."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    receiver = node.func.value
    if node.func.attr == "connect" and isinstance(receiver, ast.Name) and receiver.id == "websockets":
        return "GET"  # a WebSocket subscription starts with an HTTP GET upgrade
    method = CLIENT_METHODS.get(node.func.attr)
    name = receiver.id if isinstance(receiver, ast.Name) else (
        receiver.attr if isinstance(receiver, ast.Attribute) else "")
    return method if method and "client" in name.lower() else None


class _Unit:
    """What one top-level function (with nested functions) does with paths and requests."""

    def __init__(
        self, func: ast.AST, consts: dict[str, str], local_funcs: set[str],
        collections: dict[str, list[str]] | None = None,
    ):
        collections = collections or {}
        self.direct: set[str] = set()
        self.calls: set[str] = set()
        self.exact: set[Ref] = set()
        self.loose: set[str] = set()
        local_values: dict[str, ast.AST] = {}
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                local_values[node.targets[0].id] = node.value
        skip: set[int] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in local_funcs:
                self.calls.add(node.func.id)
            method = _client_method(node)
            if method is None:
                continue
            self.direct.add(method)
            if not node.args:
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Name) and arg.id in local_values and arg.id not in consts:
                arg = local_values[arg.id]
            text = _path_of(_literal(arg, consts))
            if text:
                self.exact.add((method, text))
                skip.add(id(arg))
        for node in ast.walk(func):
            if id(node) in skip:
                skip.update(id(child) for child in ast.iter_child_nodes(node))
                continue
            if isinstance(node, (ast.JoinedStr, ast.BinOp)):
                skip.update(id(child) for child in ast.iter_child_nodes(node))
            if isinstance(node, ast.Name) and node.id in collections:
                self.loose.update(collections[node.id])
            text = _path_of(_literal(node, consts))
            if text:
                self.loose.add(text)


def _closure(start: str, edges: dict[str, set[str]]) -> set[str]:
    seen, stack = set(), [start]
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def module_references(
    tree: ast.Module, imported: dict[str, str] | None = None,
    imported_seqs: dict[str, list[str]] | None = None,
) -> set[Ref]:
    """(method, path) pairs one module requests, with templated segments expanded."""
    consts = module_constants(tree, imported)
    seqs = {**(imported_seqs or {}), **module_sequences(tree)}
    collections = module_path_collections(tree, consts)
    funcs = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[f"{node.name}.{item.name}"] = item
    local_names = {name for name in funcs if "." not in name}
    units = {name: _Unit(func, consts, local_names, collections) for name, func in funcs.items()}
    calls = {name: unit.calls for name, unit in units.items()}
    callers: dict[str, set[str]] = {}
    for name, called in calls.items():
        for callee in called:
            callers.setdefault(callee, set()).add(name)

    def down(name: str) -> set[str]:
        methods = set(units[name].direct)
        for callee in _closure(name, calls):
            if callee in units:
                methods |= units[callee].direct
        return methods

    refs: set[Ref] = set()
    for name, unit in units.items():
        refs |= unit.exact
        if not unit.loose:
            continue
        methods = down(name)
        for caller in _closure(name, callers):
            methods |= down(caller)
        refs |= {(m, text) for m in methods for text in unit.loose}
    return {(m, path) for m, raw in refs for path in expand_placeholders(raw, seqs)}


def _parse(file: Path) -> ast.Module | None:
    try:
        return ast.parse(file.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _source_files(paths: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files += sorted(path.rglob("*.py")) if path.is_dir() else ([path] if path.is_file() else [])
    return files


def _module_name(file: Path) -> str | None:
    """Dotted module name for a file under src/ (None elsewhere)."""
    try:
        rel = file.resolve().relative_to((REPO_ROOT / "src").resolve())
    except ValueError:
        return None
    return ".".join(rel.with_suffix("").parts)


def _imports(tree: ast.Module, known: dict[str, tuple[dict, dict]]) -> tuple[dict, dict]:
    """Constants and string collections this module imports from other scanned modules."""
    consts: dict[str, str] = {}
    seqs: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or node.module not in known:
            continue
        their_consts, their_seqs = known[node.module]
        for alias in node.names:
            local = alias.asname or alias.name
            if alias.name in their_consts:
                consts[local] = their_consts[alias.name]
            if alias.name in their_seqs:
                seqs[local] = their_seqs[alias.name]
    return consts, seqs


def collect_tool_references(paths: Iterable[Path] = (TOOLS_DIR, *EXTRA_FILES)) -> set[Ref]:
    """Every (method, path) the given modules or directories request."""
    trees = [(file, tree) for file in _source_files(paths) if (tree := _parse(file)) is not None]
    known = {
        name: (module_constants(tree), module_sequences(tree))
        for file, tree in trees if (name := _module_name(file))
    }
    refs: set[Ref] = set()
    for _, tree in trees:
        consts, seqs = _imports(tree, known)
        refs |= module_references(tree, consts, seqs)
    return refs


def collect_tool_literals(tools_dir: Path = TOOLS_DIR) -> set[str]:
    """Return raw string literals that look like URL paths from all tool modules (any use)."""
    found: set[str] = set()
    for file in _source_files([tools_dir]):
        tree = _parse(file)
        if tree is None:
            continue
        consts = module_constants(tree)
        for node in ast.walk(tree):
            text = _literal(node, consts)
            if _is_path(text):
                found.add(text)
    return found


def spec_operations(spec: dict) -> list[tuple[str, str, str | None]]:
    ops = []
    paths = spec.get("paths") or {}
    for key in spec_diff.extract_operations(spec):
        method, path = key.split(" ", 1)
        op = (paths.get(path) or {}).get(method.lower())
        op_id = op.get("operationId") if isinstance(op, dict) else None
        ops.append((method, path, op_id))
    return sorted(ops, key=lambda item: (item[1], item[0]))


def compute_coverage(service: str, spec: dict, refs: Iterable[Ref | str], label: str | None = None) -> dict:
    """Coverage by method and path. A bare string ref matches any method (path-only input)."""
    prefix = PREFIXES.get(service, "")
    by_method: set[tuple[str | None, str]] = set()
    for ref in refs:
        method, text = (None, ref) if isinstance(ref, str) else ref
        if not prefix or text.startswith(prefix):
            by_method.add((method, normalize_path(text, prefix)))
    paths = {path for _, path in by_method}
    rows = []
    for method, path, op_id in spec_operations(spec):
        norm = normalize_path(path)
        covered = (method, norm) in by_method or (None, norm) in by_method
        rows.append({"method": method, "path": path, "operation_id": op_id,
                     "covered": covered, "path_covered": norm in paths})
    total = len(rows)

    def pct(n: int) -> float:
        return round(100.0 * n / total, 1) if total else 0.0

    covered = sum(1 for row in rows if row["covered"])
    path_covered = sum(1 for row in rows if row["path_covered"])
    return {"service": label or service, "rows": rows, "covered": covered, "total": total,
            "percent": pct(covered), "path_covered": path_covered, "path_percent": pct(path_covered)}


def render_markdown(reports: list[dict]) -> str:
    lines = ["# OpenAPI coverage (by HTTP method and path)", ""]
    for report in reports:
        lines += [
            f"## {report['service']}: {report['percent']}% ({report['covered']}/{report['total']})",
            "",
            f"Path-only: {report.get('path_percent', report['percent'])}%.",
            "",
            "| Method | Path | operationId | Covered |",
            "|--------|------|-------------|---------|",
        ]
        for row in report["rows"]:
            mark = "yes" if row["covered"] else "no"
            lines.append(f"| {row['method']} | `{row['path']}` | {row.get('operation_id') or ''} | {mark} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_reports(
    spec_dir: Path = spec_diff.SPEC_DIR, tools_dir: Path = TOOLS_DIR, extra_files: Iterable[Path] = EXTRA_FILES,
) -> list[dict]:
    refs = collect_tool_references([tools_dir, *extra_files])
    reports = []
    for service in spec_diff.SERVICES:
        vendored = spec_diff.find_vendored(service, spec_dir)
        if vendored is None:
            continue
        version, path = vendored
        report = compute_coverage(service, spec_diff.load_spec(path), refs, f"{service} {version}")
        reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report OpenAPI operation coverage by method and path.")
    parser.add_argument("--check-min", type=float, metavar="N", help="exit 1 if any spec is below N percent")
    args = parser.parse_args(argv)

    reports = load_reports()
    print(render_markdown(reports), end="")
    if args.check_min is not None:
        low = [r for r in reports if r["percent"] < args.check_min]
        for report in low:
            print(f"FAIL: {report['service']} coverage {report['percent']}% < {args.check_min}%", file=sys.stderr)
        if low:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
