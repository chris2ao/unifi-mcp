"""Tests for scripts/gen_tool_docs.py (docs/TOOLS.md generator)."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from unifi_mcp.tools._registry import ToolModule

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_tool_docs.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_tool_docs_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


async def list_widgets(client) -> list[dict]:
    """List widgets | with a pipe.

    More detail that is not part of the description.
    """
    return []


async def delete_widget(client, widget_id: str, confirm: bool = False) -> dict:
    """

    Delete a widget (Tier 2).
    """
    return {}


async def undocumented(client) -> dict:
    return {}


async def get_cam(client) -> dict:
    """Get a camera."""
    return {}


FAKE_MODULES = [
    ToolModule("network", "widgets", "core", (list_widgets, delete_widget),
               MappingProxyType({"delete_widget": "widgets"})),
    ToolModule("network", "misc", "insights", (undocumented,)),
    ToolModule("protect", "cams", "cameras", (get_cam,)),
]


# --- helpers ---

def test_first_doc_line(gen):
    assert gen.first_doc_line(list_widgets) == "List widgets | with a pipe."
    assert gen.first_doc_line(delete_widget) == "Delete a widget (Tier 2)."
    assert gen.first_doc_line(undocumented) == "(no description)"


def test_cell_escapes_pipes_and_whitespace(gen):
    assert gen.cell("a | b\n  c") == "a \\| b c"


def test_is_tracked_module_and_package(gen):
    tracked = {"src/unifi_mcp/tools/network/zbf.py", "src/unifi_mcp/tools/protect/pkg/__init__.py"}
    assert gen.is_tracked("network", "zbf", tracked) is True
    assert gen.is_tracked("protect", "pkg", tracked) is True
    assert gen.is_tracked("network", "firewall", tracked) is False


def test_tracked_tool_paths_parses_git_output(gen, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["git", "ls-files", "--cached"]
        return SimpleNamespace(returncode=0, stdout="src/unifi_mcp/tools/network/a.py\n\n",
                               stderr="")

    monkeypatch.setattr(gen.subprocess, "run", fake_run)
    assert gen.tracked_tool_paths() == {"src/unifi_mcp/tools/network/a.py"}


def test_tracked_tool_paths_git_failure(gen, monkeypatch):
    monkeypatch.setattr(gen.subprocess, "run", lambda cmd, **kw: SimpleNamespace(
        returncode=128, stdout="", stderr="fatal: not a git repository"))
    with pytest.raises(RuntimeError, match="not a git repository"):
        gen.tracked_tool_paths()


def test_tracked_tool_paths_git_missing(gen, monkeypatch):
    def boom(cmd, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gen.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="git ls-files failed"):
        gen.tracked_tool_paths()


def test_tracked_tool_paths_real_repo(gen):
    paths = gen.tracked_tool_paths()
    assert "src/unifi_mcp/tools/network/zbf.py" in paths


# --- collection and tiers ---

def test_build_tool_docs_uses_merged_tiers(gen):
    docs = {d.name: d for d in gen.build_tool_docs(FAKE_MODULES)}
    assert docs["delete_widget"].tier == 2
    assert docs["list_widgets"].tier == 1
    assert docs["list_widgets"].group == "core"
    assert docs["get_cam"].product == "protect"
    assert docs["undocumented"].description == "(no description)"


def test_collect_real_modules_with_legacy_tiers(gen):
    modules, errors = gen.collect_modules(None)
    assert errors == []
    docs = {d.name: d for d in gen.build_tool_docs(modules)}
    assert docs["create_network"].tier == 2
    assert docs["get_system_info"].tier == 1
    assert docs["get_system_info"].group == "core"
    assert docs["list_firewall_rules"].group == "security"


def test_collect_respects_tracked_set(gen):
    tracked = {"src/unifi_mcp/tools/network/zbf.py"}
    modules, errors = gen.collect_modules(tracked)
    assert errors == []
    assert [m.key for m in modules] == ["network.zbf"]


def test_untracked_modules_lists_left_out(gen):
    left_out = gen.untracked_modules({"src/unifi_mcp/tools/network/zbf.py"})
    assert "network.zbf" not in left_out
    assert "network.firewall" in left_out


# --- rendering ---

def test_render_layout_and_counts(gen):
    text = gen.render(gen.build_tool_docs(FAKE_MODULES))
    assert text.startswith("# UniFi MCP Tools\n")
    assert "Do not edit by hand" in text
    assert "tracked in git" in text
    assert "| Network | core | 2 | 1 | 1 |" in text
    assert "| Network | insights | 1 | 1 | 0 |" in text
    assert "| **Network** | **all** | **3** | **2** | **1** |" in text
    assert "| **Total** | | **4** | **3** | **1** |" in text
    assert "## Network" in text and "## Protect" in text
    assert "## Access" not in text  # empty products are omitted
    assert "Loaded by `load_network_tools`." in text
    assert "### Network: core" in text
    assert "| `delete_widget` | 2 | Delete a widget (Tier 2). |" in text
    assert "| `list_widgets` | 1 | List widgets \\| with a pipe. |" in text
    assert text.index("### Network: core") < text.index("### Network: insights")
    assert text.index("## Network") < text.index("## Protect")
    assert text.endswith("|\n")
    assert "\u2014" not in text  # no em dashes in generated docs


def test_render_is_deterministic_and_marks_scope(gen):
    docs = gen.build_tool_docs(FAKE_MODULES)
    assert gen.render(docs) == gen.render(list(docs))
    assert "including untracked" in gen.render(docs, include_untracked=True)


def test_totals_line(gen):
    line = gen.totals_line(gen.build_tool_docs(FAKE_MODULES))
    assert line == "4 tools (network 3, protect 1): 3 Tier 1, 1 Tier 2."
    assert gen.totals_line([]) == "0 tools (none): 0 Tier 1, 0 Tier 2."


# --- main ---

@pytest.fixture
def fake_sources(gen, monkeypatch):
    monkeypatch.setattr(gen, "collect_modules", lambda tracked: (list(FAKE_MODULES), []))
    monkeypatch.setattr(gen, "tracked_tool_paths", lambda: set())
    monkeypatch.setattr(gen, "dirty_tool_paths", lambda: set())
    monkeypatch.setattr(gen, "untracked_modules", lambda tracked: ["network.wip"])


def test_main_writes_then_check_passes(gen, fake_sources, tmp_path, capsys):
    out = tmp_path / "docs" / "TOOLS.md"
    assert gen.main(["--output", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == gen.render(gen.build_tool_docs(FAKE_MODULES))
    captured = capsys.readouterr()
    assert "4 tools" in captured.out
    assert "network.wip" in captured.err  # tells the user what was left out
    assert gen.main(["--check", "--output", str(out)]) == 0
    assert "up to date" in capsys.readouterr().out


def test_check_fails_when_stale_or_missing(gen, fake_sources, tmp_path, capsys):
    out = tmp_path / "TOOLS.md"
    assert gen.main(["--check", "--output", str(out)]) == 1
    assert "missing" in capsys.readouterr().err
    out.write_text("# stale\n", encoding="utf-8")
    assert gen.main(["--check", "--output", str(out)]) == 1
    assert "out of date" in capsys.readouterr().err
    assert out.read_text(encoding="utf-8") == "# stale\n"  # --check never writes


def test_all_mode_skips_git(gen, monkeypatch, tmp_path):
    seen = []

    def no_git():
        raise AssertionError("git must not be consulted with --all")

    monkeypatch.setattr(gen, "tracked_tool_paths", no_git)
    monkeypatch.setattr(gen, "collect_modules",
                        lambda tracked: seen.append(tracked) or (list(FAKE_MODULES), []))
    out = tmp_path / "TOOLS.md"
    assert gen.main(["--all", "--output", str(out)]) == 0
    assert seen == [None]
    assert "including untracked" in out.read_text(encoding="utf-8")


def test_import_errors_exit_2(gen, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gen, "collect_modules",
                        lambda tracked: ([], ["network.broken: SyntaxError: bad"]))
    out = tmp_path / "TOOLS.md"
    assert gen.main(["--all", "--output", str(out)]) == 2
    assert "network.broken" in capsys.readouterr().err
    assert not out.exists()


def test_git_failure_exits_2(gen, monkeypatch, tmp_path, capsys):
    def broken():
        raise RuntimeError("git ls-files failed: nope")

    monkeypatch.setattr(gen, "tracked_tool_paths", broken)
    assert gen.main(["--output", str(tmp_path / "TOOLS.md")]) == 2
    assert "git ls-files failed" in capsys.readouterr().err


def test_display_path(gen, tmp_path):
    assert gen._display(gen.DEFAULT_OUTPUT) == "docs/TOOLS.md"
    assert gen._display(tmp_path / "x.md") == str(tmp_path / "x.md")


def test_script_runs_as_cli(tmp_path):
    out = tmp_path / "TOOLS.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--all", "--output", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "tools (" in result.stdout
    text = out.read_text(encoding="utf-8")
    assert "### Network: core" in text
    assert "`get_system_info`" in text


def test_unstaged_tracked_edits_exit_2(gen, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(gen, "tracked_tool_paths", lambda: {"src/unifi_mcp/tools/network/a.py"})
    monkeypatch.setattr(gen, "dirty_tool_paths", lambda: {"src/unifi_mcp/tools/network/a.py"})
    out = tmp_path / "TOOLS.md"
    assert gen.main(["--output", str(out)]) == 2
    err = capsys.readouterr().err
    assert "unstaged edits" in err and "network/a.py" in err
    assert not out.exists()


def test_dirty_tool_paths_parses_git_output(gen, monkeypatch):
    monkeypatch.setattr(
        gen.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="src/unifi_mcp/tools/x.py\n", stderr=""),
    )
    assert gen.dirty_tool_paths() == {"src/unifi_mcp/tools/x.py"}


def test_dirty_tool_paths_git_failure(gen, monkeypatch):
    monkeypatch.setattr(
        gen.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=128, stdout="", stderr="fatal"),
    )
    with pytest.raises(RuntimeError, match="git diff failed"):
        gen.dirty_tool_paths()


def test_committed_tools_md_is_current(gen, capsys):
    """Staleness guard: docs/TOOLS.md must match the tracked tool modules."""
    code = gen.main(["--check"])
    out = capsys.readouterr()
    if code == 2:
        pytest.skip(f"cannot verify in this checkout: {out.err.strip()[:200]}")
    assert code == 0, out.err
