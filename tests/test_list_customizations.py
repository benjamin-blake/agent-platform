"""Tests for scripts/list_customizations.py."""

from __future__ import annotations

# Import functions under test — use importlib to handle hyphenated package names
import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_script(script_path: Path):
    """Load a script module by path."""
    spec = importlib.util.spec_from_file_location("list_customizations", script_path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "list_customizations.py"


@pytest.fixture()
def mod():
    return _load_script(SCRIPT_PATH)


# ---------------------------------------------------------------------------
# parse_frontmatter tests
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid(mod):
    content = "---\nname: my-agent\ndescription: Does something\nmodel: GPT-4.1\n---\n\n## Body"
    result = mod.parse_frontmatter(content)
    assert result["name"] == "my-agent"
    assert result["description"] == "Does something"
    assert result["model"] == "GPT-4.1"


def test_parse_frontmatter_missing_name(mod):
    content = "---\ndescription: Does something\nmodel: GPT-4.1\n---\n"
    result = mod.parse_frontmatter(content)
    assert "name" not in result
    assert result["description"] == "Does something"


def test_parse_frontmatter_missing_description(mod):
    content = "---\nname: my-agent\nmodel: GPT-4.1\n---\n"
    result = mod.parse_frontmatter(content)
    assert result["name"] == "my-agent"
    assert "description" not in result


def test_parse_frontmatter_no_frontmatter(mod):
    content = "# Just markdown\nNo frontmatter here."
    result = mod.parse_frontmatter(content)
    assert result == {}


def test_parse_frontmatter_malformed_yaml(mod):
    content = "---\nname: [unclosed\n---\n"
    result = mod.parse_frontmatter(content)
    assert result == {}


def test_parse_frontmatter_unclosed_markers(mod):
    content = "---\nname: my-agent\n"
    result = mod.parse_frontmatter(content)
    assert result == {}


# ---------------------------------------------------------------------------
# build_entry tests
# ---------------------------------------------------------------------------


def test_build_entry_valid_frontmatter(tmp_path: Path, mod):
    agent_file = tmp_path / "test.agent.md"
    agent_file.write_text(
        "---\nname: test-agent\ndescription: Test agent\nmodel: GPT-4.1\n---\n## Body",
        encoding="utf-8",
    )
    repo_root_patch = patch.object(mod, "REPO_ROOT", tmp_path)
    with repo_root_patch:
        entry = mod.build_entry(agent_file)
    assert entry["name"] == "test-agent"
    assert entry["description"] == "Test agent"
    assert entry["model"] == "GPT-4.1"
    assert entry["path"].endswith("test.agent.md")
    assert entry["last_modified"] is not None


def test_build_entry_missing_name_has_null(tmp_path: Path, mod):
    agent_file = tmp_path / "no-name.agent.md"
    agent_file.write_text(
        "---\ndescription: Test\nmodel: GPT-4.1\n---\n",
        encoding="utf-8",
    )
    with patch.object(mod, "REPO_ROOT", tmp_path):
        entry = mod.build_entry(agent_file)
    assert entry["name"] is None
    assert entry["description"] == "Test"


def test_build_entry_missing_description_has_null(tmp_path: Path, mod):
    agent_file = tmp_path / "no-desc.agent.md"
    agent_file.write_text(
        "---\nname: test-agent\nmodel: GPT-4.1\n---\n",
        encoding="utf-8",
    )
    with patch.object(mod, "REPO_ROOT", tmp_path):
        entry = mod.build_entry(agent_file)
    assert entry["description"] is None


def test_build_entry_no_frontmatter_returns_nulls(tmp_path: Path, mod):
    agent_file = tmp_path / "bare.agent.md"
    agent_file.write_text("# No frontmatter\n", encoding="utf-8")
    with patch.object(mod, "REPO_ROOT", tmp_path):
        entry = mod.build_entry(agent_file)
    assert entry["name"] is None
    assert entry["description"] is None
    assert entry["model"] is None


# ---------------------------------------------------------------------------
# scan_customizations tests
# ---------------------------------------------------------------------------


def test_scan_customizations_finds_prompt_and_agent_files(tmp_path: Path, mod):
    github_dir = tmp_path / ".github"
    prompts_dir = github_dir / "prompts"
    agents_dir = github_dir / "agents"
    prompts_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)

    frontmatter = "---\nname: {name}\ndescription: {name} desc\nmodel: GPT-4.1\n---\n"
    (prompts_dir / "plan.prompt.md").write_text(frontmatter.format(name="plan"), encoding="utf-8")
    (prompts_dir / "implement.prompt.md").write_text(frontmatter.format(name="implement"), encoding="utf-8")
    (agents_dir / "retro-lite.agent.md").write_text(frontmatter.format(name="retro-lite"), encoding="utf-8")

    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        entries = mod.scan_customizations()

    assert len(entries) == 3
    paths = [e["path"] for e in entries]
    assert any("plan.prompt.md" in p for p in paths)
    assert any("implement.prompt.md" in p for p in paths)
    assert any("retro-lite.agent.md" in p for p in paths)


def test_scan_customizations_sorted_by_path(tmp_path: Path, mod):
    github_dir = tmp_path / ".github"
    prompts_dir = github_dir / "prompts"
    agents_dir = github_dir / "agents"
    prompts_dir.mkdir(parents=True)
    agents_dir.mkdir(parents=True)

    frontmatter = "---\nname: {n}\ndescription: d\nmodel: GPT-4.1\n---\n"
    for name in ("zebra.prompt.md", "alpha.prompt.md"):
        (prompts_dir / name).write_text(frontmatter.format(n=name), encoding="utf-8")

    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        entries = mod.scan_customizations()

    paths = [e["path"] for e in entries]
    assert paths == sorted(paths)


def test_scan_customizations_empty_dirs(tmp_path: Path, mod):
    github_dir = tmp_path / ".github"
    (github_dir / "prompts").mkdir(parents=True)
    (github_dir / "agents").mkdir(parents=True)

    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        entries = mod.scan_customizations()

    assert entries == []


def test_scan_customizations_missing_dirs_returns_empty(tmp_path: Path, mod):
    github_dir = tmp_path / ".github"
    github_dir.mkdir()
    # No prompts/ or agents/ subdirectories

    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        entries = mod.scan_customizations()

    assert entries == []


# ---------------------------------------------------------------------------
# --output argument handling tests
# ---------------------------------------------------------------------------


def test_main_output_argument(tmp_path: Path, mod, monkeypatch):
    github_dir = tmp_path / ".github"
    (github_dir / "prompts").mkdir(parents=True)
    (github_dir / "agents").mkdir(parents=True)

    output_file = tmp_path / "custom-manifest.json"

    monkeypatch.setattr(sys, "argv", ["list_customizations.py", "--output", str(output_file)])
    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        mod.main()

    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert isinstance(data, list)


def test_main_default_output_location(tmp_path: Path, mod, monkeypatch):
    github_dir = tmp_path / ".github"
    (github_dir / "prompts").mkdir(parents=True)
    (github_dir / "agents").mkdir(parents=True)
    (tmp_path / "logs").mkdir()

    monkeypatch.setattr(sys, "argv", ["list_customizations.py"])
    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        mod.main()

    default_output = tmp_path / "logs" / ".customizations-manifest.json"
    assert default_output.exists()


# ---------------------------------------------------------------------------
# build_decisions_index tests
# ---------------------------------------------------------------------------

DECISIONS_CONTENT = """\
# Open Decisions

## Decision 21: Per-Step Retro-Lite Retention (Decided)

Some context.

**Status:** Decided -- March 2026

---

## Decision 22: Cron Review System Architecture (Decided)

Some other context.

**Status:** Decided -- March 2026

---

## Python-Only Scripting (Decided)

Context here.

**Status:** Decided -- March 2026

---

## Open Decisions

This heading should be skipped.

## Rejected Cron Suggestions

This heading should also be skipped.
"""


def test_build_decisions_index_explicit_numbered_entries(mod, tmp_path):
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(DECISIONS_CONTENT, encoding="utf-8")

    index = mod.build_decisions_index(decisions_path)

    # Should find Decision 21 and Decision 22 with explicit IDs
    ids = [e["id"] for e in index]
    assert "dec-021" in ids
    assert "dec-022" in ids


def test_build_decisions_index_explicit_ids_not_duplicated(mod, tmp_path):
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(DECISIONS_CONTENT, encoding="utf-8")

    index = mod.build_decisions_index(decisions_path)

    ids = [e["id"] for e in index]
    assert len(ids) == len(set(ids)), "Duplicate IDs found in decisions index"


def test_build_decisions_index_skips_reserved_headings(mod, tmp_path):
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(DECISIONS_CONTENT, encoding="utf-8")

    index = mod.build_decisions_index(decisions_path)

    titles = [e["title"] for e in index]
    assert "Open Decisions" not in titles
    assert "Rejected Cron Suggestions" not in titles


def test_build_decisions_index_status_decided(mod, tmp_path):
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(DECISIONS_CONTENT, encoding="utf-8")

    index = mod.build_decisions_index(decisions_path)

    for entry in index:
        assert entry["status"] in ("Decided", "Open", "Unknown"), f"Unexpected status: {entry['status']}"

    decided = [e for e in index if e["status"] == "Decided"]
    assert len(decided) >= 2


def test_build_decisions_index_keywords_extracted(mod, tmp_path):
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(DECISIONS_CONTENT, encoding="utf-8")

    index = mod.build_decisions_index(decisions_path)

    for entry in index:
        assert "keywords" in entry
        assert isinstance(entry["keywords"], list)


def test_build_decisions_index_missing_file_returns_empty(mod, tmp_path):
    decisions_path = tmp_path / "DECISIONS.md"  # Does not exist

    index = mod.build_decisions_index(decisions_path)

    assert index == []


def test_build_decisions_index_auto_numbering_avoids_explicit_ids(mod, tmp_path):
    """Auto-numbered IDs must not collide with explicitly numbered decision IDs."""
    content = """\
# Open Decisions

## Decision 21: Explicit Decision (Decided)

**Status:** Decided -- March 2026

---

## Some Un-numbered Decision (Decided)

**Status:** Decided -- March 2026
"""
    decisions_path = tmp_path / "DECISIONS.md"
    decisions_path.write_text(content, encoding="utf-8")

    index = mod.build_decisions_index(decisions_path)

    ids = [e["id"] for e in index]
    assert len(ids) == len(set(ids)), "Auto-numbered ID collided with explicit dec-021"
    assert "dec-021" in ids  # The explicit one is present


def test_build_decisions_index_with_decisions_flag(mod, tmp_path, monkeypatch):
    """--with-decisions flag writes .decisions-index.jsonl to repo root."""
    import json as json_module

    github_dir = tmp_path / ".github"
    (github_dir / "prompts").mkdir(parents=True)
    (github_dir / "agents").mkdir(parents=True)
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)

    decisions_path = tmp_path / "docs" / "DECISIONS.md"
    decisions_path.write_text(DECISIONS_CONTENT, encoding="utf-8")

    manifest_output = tmp_path / "manifest.json"
    monkeypatch.setattr(sys, "argv", ["list_customizations.py", "--output", str(manifest_output), "--with-decisions"])
    with patch.object(mod, "REPO_ROOT", tmp_path), patch.object(mod, "GITHUB_DIR", github_dir):
        mod.main()

    index_path = tmp_path / "logs" / ".decisions-index.jsonl"
    assert index_path.exists()

    lines = [line for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2  # At least Decision 21 and Decision 22
    first = json_module.loads(lines[0])
    assert "id" in first
    assert "title" in first
    assert "status" in first
