#!/usr/bin/env python3
"""Report which vendored OpenAPI operations are referenced by unifi-mcp tool modules.

An operation counts as covered when any string literal under src/unifi_mcp/tools
contains its path (after normalizing path params and the integration prefixes).
Top-level string constants such as `_BASE = "/proxy/..."` are substituted into
f-strings and `+` concatenations, so paths built from them are found.
Matching is by path only, not HTTP method. Standard library only.

Usage:
    python scripts/spec_coverage.py
    python scripts/spec_coverage.py --check-min 60
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_diff  # noqa: E402

REPO_ROOT = spec_diff.REPO_ROOT
TOOLS_DIR = REPO_ROOT / "src" / "unifi_mcp" / "tools"
PREFIXES = {
    "network": "/proxy/network/integration",
    "protect": "/proxy/protect/integration",
    "site-manager": "",
}


def normalize_path(path: str, prefix: str = "") -> str:
    """Normalize a path: strip query/prefix, collapse every {param} to {}."""
    path = path.split("?", 1)[0].split("#", 1)[0]
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    path = re.sub(r"\{\{[^{}]*\}\}|\{[^{}]*\}", "{}", path)
    return path.rstrip("/") or "/"


def _literal(node: ast.AST, consts: dict[str, str] | None = None) -> str | None:
    """Best-effort string value of a node. Module constants in `consts` are substituted."""
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
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name) \
                    and value.value.id in consts:
                parts.append(consts[value.value.id])
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


def module_constants(tree: ast.Module) -> dict[str, str]:
    """Collect top-level `NAME = "..."` style assignments, resolving references between them."""
    consts: dict[str, str] = {}
    assigns = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ] + [
        node for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value
    ]
    for _ in range(3):  # a few passes resolve constants built from earlier constants
        for node in assigns:
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            value = _literal(node.value, consts)
            if value is not None:
                consts[target.id] = value
    return consts


def collect_tool_literals(tools_dir: Path = TOOLS_DIR) -> set[str]:
    """Return raw string literals that look like URL paths from all tool modules."""
    found: set[str] = set()
    for file in sorted(tools_dir.rglob("*.py")):
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        consts = module_constants(tree)
        for node in ast.walk(tree):
            text = _literal(node, consts)
            if text and text.startswith("/") and len(text) > 1:
                found.add(text)
    return found


def spec_operations(spec: dict) -> list[tuple[str, str]]:
    ops = []
    for key in spec_diff.extract_operations(spec):
        method, path = key.split(" ", 1)
        ops.append((method, path))
    return sorted(ops, key=lambda item: (item[1], item[0]))


def compute_coverage(service: str, spec: dict, literals: set[str], label: str | None = None) -> dict:
    prefix = PREFIXES.get(service, "")
    referenced = {
        normalize_path(text, prefix)
        for text in literals
        if not prefix or text.startswith(prefix)
    }
    rows = []
    for method, path in spec_operations(spec):
        rows.append({"method": method, "path": path, "covered": normalize_path(path) in referenced})
    covered = sum(1 for row in rows if row["covered"])
    percent = round(100.0 * covered / len(rows), 1) if rows else 0.0
    return {"service": label or service, "rows": rows, "covered": covered, "total": len(rows), "percent": percent}


def render_markdown(reports: list[dict]) -> str:
    lines = ["# OpenAPI coverage", ""]
    for report in reports:
        lines += [
            f"## {report['service']}: {report['percent']}% ({report['covered']}/{report['total']})",
            "",
            "| Method | Path | Covered |",
            "|--------|------|---------|",
        ]
        for row in report["rows"]:
            mark = "yes" if row["covered"] else "no"
            lines.append(f"| {row['method']} | `{row['path']}` | {mark} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_reports(spec_dir: Path = spec_diff.SPEC_DIR, tools_dir: Path = TOOLS_DIR) -> list[dict]:
    literals = collect_tool_literals(tools_dir)
    reports = []
    for service in spec_diff.SERVICES:
        vendored = spec_diff.find_vendored(service, spec_dir)
        if vendored is None:
            continue
        version, path = vendored
        report = compute_coverage(service, spec_diff.load_spec(path), literals, f"{service} {version}")
        reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report OpenAPI operation coverage by tool modules.")
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
