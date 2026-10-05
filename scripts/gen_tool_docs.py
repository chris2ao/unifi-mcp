#!/usr/bin/env python3
"""Generate docs/TOOLS.md from the auto-discovered tool modules.

Every tool is listed with its product, group, safety tier (from the merged
Tier 2 map: legacy declarations plus module-level TIER2_TOOLS) and the first
line of its docstring. By default only tool modules tracked or staged in git
are included, so untracked work in progress never leaks into the generated file.
Tracked modules are imported from the working tree, so the script refuses to run
(exit 2) when a tracked tool module has unstaged edits: those edits could belong to a
later release. Stage the edits or generate from a clean checkout (git worktree).

Usage:
    uv run python scripts/gen_tool_docs.py           # write docs/TOOLS.md
    uv run python scripts/gen_tool_docs.py --all     # include untracked modules too
    uv run python scripts/gen_tool_docs.py --check   # exit 1 if docs/TOOLS.md is stale

Exit codes: 0 ok, 1 stale or missing (--check), 2 a module failed to import
or git could not list tracked files.
"""

from __future__ import annotations

import argparse
import inspect
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = str(REPO_ROOT / "src")
if _SRC_DIR not in sys.path:
    # Document the working tree, not whatever copy happens to be installed.
    sys.path.insert(0, _SRC_DIR)

from unifi_mcp.safety import SafetyManager, SafetyTier  # noqa: E402
from unifi_mcp.tools._registry import (  # noqa: E402
    PRODUCTS,
    ToolModule,
    discover_module_names,
    merge_module_tiers,
    scan_tool_modules,
)

DEFAULT_OUTPUT = REPO_ROOT / "docs" / "TOOLS.md"
TOOLS_DIR = "src/unifi_mcp/tools"
DOC_PRODUCTS: tuple[str, ...] = (*PRODUCTS, "cloud")
PRODUCT_TITLES = {
    "network": "Network",
    "protect": "Protect",
    "access": "Access",
    "cloud": "Site Manager (cloud)",
}
LOADERS = {
    "network": "load_network_tools",
    "protect": "load_protect_tools",
    "access": "load_access_tools",
    "cloud": "load_cloud_tools",
}
NO_DESCRIPTION = "(no description)"


@dataclass(frozen=True)
class ToolDoc:
    name: str
    product: str
    group: str
    module: str
    tier: int
    description: str


# ------------------------------------------------------------------ helpers


def first_doc_line(fn: Callable[..., Any]) -> str:
    """First non-empty docstring line of a tool (its MCP description)."""
    doc = inspect.getdoc(fn) or ""
    for line in doc.splitlines():
        if line.strip():
            return line.strip()
    return NO_DESCRIPTION


def cell(text: str) -> str:
    """Make text safe for a single markdown table cell."""
    return " ".join(text.split()).replace("|", "\\|")


def tracked_tool_paths(repo_root: Path = REPO_ROOT) -> set[str]:
    """Paths under src/unifi_mcp/tools that are tracked or staged in git."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--", TOOLS_DIR],
            cwd=repo_root, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git ls-files failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {result.stderr.strip() or result.returncode}")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def dirty_tool_paths(repo_root: Path = REPO_ROOT) -> set[str]:
    """Tracked paths under src/unifi_mcp/tools with unstaged working-tree edits."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--", TOOLS_DIR],
            cwd=repo_root, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git diff failed: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip() or result.returncode}")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def is_tracked(product: str, module: str, tracked: set[str]) -> bool:
    base = f"{TOOLS_DIR}/{product}/{module}"
    return f"{base}.py" in tracked or f"{base}/__init__.py" in tracked


# --------------------------------------------------------------- collection


def _include_filter(product: str, tracked: set[str] | None) -> Callable[[str], bool] | None:
    if tracked is None:
        return None
    return lambda name: is_tracked(product, name, tracked)


def collect_modules(tracked: set[str] | None) -> tuple[list[ToolModule], list[str]]:
    """Scan every documented product; `tracked=None` means include all modules."""
    modules: list[ToolModule] = []
    errors: list[str] = []
    for product in DOC_PRODUCTS:
        found, failed = scan_tool_modules(product, include=_include_filter(product, tracked))
        modules = [*modules, *found]
        errors = [*errors, *(f"{e.product}.{e.name}: {e.error}" for e in failed)]
    return modules, errors


def build_tool_docs(modules: Iterable[ToolModule]) -> list[ToolDoc]:
    """One ToolDoc per tool, with the tier taken from the merged Tier 2 map."""
    module_list = list(modules)
    manager = SafetyManager()
    merge_module_tiers(manager, module_list)
    return [
        ToolDoc(
            name=fn.__name__,
            product=module.product,
            group=module.group,
            module=module.name,
            tier=2 if manager.get_tier(fn.__name__) == SafetyTier.PREVIEW_CONFIRM else 1,
            description=first_doc_line(fn),
        )
        for module in module_list
        for fn in module.tools
    ]


def untracked_modules(tracked: set[str]) -> list[str]:
    """Discovered modules that the tracked-only mode leaves out."""
    return [
        f"{product}.{name}"
        for product in DOC_PRODUCTS
        for name in discover_module_names(product)
        if not is_tracked(product, name, tracked)
    ]


# ---------------------------------------------------------------- rendering


def _ordered_groups(tools: list[ToolDoc]) -> list[tuple[str, str]]:
    seen = {(t.product, t.group) for t in tools}
    return [(p, g) for p in DOC_PRODUCTS for g in sorted(g for q, g in seen if q == p)]


def _counts(tools: list[ToolDoc]) -> tuple[int, int, int]:
    tier2 = sum(1 for t in tools if t.tier == 2)
    return len(tools), len(tools) - tier2, tier2


def _summary_rows(tools: list[ToolDoc]) -> list[str]:
    rows = ["| Product | Group | Tools | Tier 1 | Tier 2 |", "|---|---|---:|---:|---:|"]
    for product in DOC_PRODUCTS:
        product_tools = [t for t in tools if t.product == product]
        if not product_tools:
            continue
        title = PRODUCT_TITLES[product]
        for _, group in [pg for pg in _ordered_groups(tools) if pg[0] == product]:
            total, t1, t2 = _counts([t for t in product_tools if t.group == group])
            rows.append(f"| {title} | {group} | {total} | {t1} | {t2} |")
        total, t1, t2 = _counts(product_tools)
        rows.append(f"| **{title}** | **all** | **{total}** | **{t1}** | **{t2}** |")
    total, t1, t2 = _counts(tools)
    rows.append(f"| **Total** | | **{total}** | **{t1}** | **{t2}** |")
    return rows


def _group_tables(tools: list[ToolDoc]) -> list[str]:
    lines: list[str] = []
    current_product = None
    for product, group in _ordered_groups(tools):
        title = PRODUCT_TITLES[product]
        if product != current_product:
            current_product = product
            lines += ["", f"## {title}", "", f"Loaded by `{LOADERS[product]}`."]
        lines += ["", f"### {title}: {group}", "",
                  "| Tool | Tier | Description |", "|---|---|---|"]
        lines += [
            f"| `{t.name}` | {t.tier} | {cell(t.description)} |"
            for t in tools if t.product == product and t.group == group
        ]
    return lines


def render(tools: list[ToolDoc], *, include_untracked: bool = False) -> str:
    scope = (
        "every tool module in the working tree, including untracked ones"
        if include_untracked else "the tool modules tracked in git"
    )
    lines = [
        "# UniFi MCP Tools",
        "",
        "<!-- Generated by scripts/gen_tool_docs.py. Do not edit by hand. -->",
        "",
        f"Generated by `scripts/gen_tool_docs.py` from {scope}. Regenerate it with "
        "`uv run python scripts/gen_tool_docs.py` after adding or changing tools; "
        "CI runs it with `--check` and fails on a stale copy.",
        "",
        "**Tier 1** tools run immediately (reads and cosmetic changes). **Tier 2** "
        "tools change configuration or disrupt service: call once with `confirm=False` "
        "to get a preview, then again with `confirm=True` and the same parameters.",
        "",
        "Loaders register tools by group, for example "
        '`load_network_tools(groups=["core"])`. `list_tool_groups` shows the groups at '
        "runtime and `UNIFI_TOOL_GROUPS` (for example `network:core,protect:cameras`) "
        "sets the default. The always-loaded server tools (loaders, `list_tool_groups`, "
        "`get_server_info`, `get_auth_report`, `get_mutation_log`) are not listed here.",
        "",
        "## Summary",
        "",
        *_summary_rows(tools),
        *_group_tables(tools),
    ]
    return "\n".join(lines) + "\n"


def totals_line(tools: list[ToolDoc]) -> str:
    per_product = ", ".join(
        f"{p} {sum(1 for t in tools if t.product == p)}"
        for p in DOC_PRODUCTS if any(t.product == p for t in tools)
    )
    total, t1, t2 = _counts(tools)
    return f"{total} tools ({per_product or 'none'}): {t1} Tier 1, {t2} Tier 2."


# --------------------------------------------------------------------- main


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate docs/TOOLS.md from the tool modules.")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the output file is missing or stale")
    parser.add_argument("--all", action="store_true",
                        help="include tool modules that are not tracked or staged in git")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="output path (default: docs/TOOLS.md)")
    return parser.parse_args(argv)


def _generate(include_all: bool) -> tuple[str, list[ToolDoc]]:
    tracked = None if include_all else tracked_tool_paths()
    if tracked is not None:
        dirty = sorted(dirty_tool_paths())
        if dirty:
            raise RuntimeError(
                "tracked tool modules have unstaged edits, which may belong to a later "
                "release: " + ", ".join(dirty) + ". Stage them or generate from a clean "
                "checkout (git worktree)."
            )
        skipped = untracked_modules(tracked)
        if skipped:
            print(f"Leaving out {len(skipped)} untracked module(s) (use --all to include): "
                  + ", ".join(skipped), file=sys.stderr)
    modules, errors = collect_modules(tracked)
    if errors:
        raise RuntimeError("Tool modules failed to import: " + "; ".join(errors))
    tools = build_tool_docs(modules)
    return render(tools, include_untracked=include_all), tools


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output: Path = args.output
    try:
        content, tools = _generate(args.all)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    name = _display(output)
    if args.check:
        current = output.read_text(encoding="utf-8") if output.exists() else None
        if current != content:
            state = "missing" if current is None else "out of date"
            print(f"{name} is {state}. Run: uv run python scripts/gen_tool_docs.py",
                  file=sys.stderr)
            print(f"Expected {totals_line(tools)}")
            return 1
        print(f"{name} is up to date: {totals_line(tools)}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {name}: {totals_line(tools)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
