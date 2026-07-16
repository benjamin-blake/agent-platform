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
# --with-decisions / build_decisions_index retirement (DAF-03 / PLAN-daf-authoring-grammar)
# ---------------------------------------------------------------------------


def test_with_decisions_flag_no_longer_accepted(mod, tmp_path, monkeypatch):
    """The dormant 4th DECISIONS.md parser is retired: --with-decisions is no longer a
    recognized argument (argparse exits 2 on an unknown flag)."""
    github_dir = tmp_path / ".github"
    (github_dir / "prompts").mkdir(parents=True)
    (github_dir / "agents").mkdir(parents=True)

    monkeypatch.setattr(sys, "argv", ["list_customizations.py", "--with-decisions"])
    with (
        patch.object(mod, "REPO_ROOT", tmp_path),
        patch.object(mod, "GITHUB_DIR", github_dir),
        pytest.raises(SystemExit),
    ):
        mod.main()


def test_build_decisions_index_no_longer_defined(mod):
    assert not hasattr(mod, "build_decisions_index")
