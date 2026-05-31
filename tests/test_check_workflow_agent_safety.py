"""Tests for scripts/check_workflow_agent_safety.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import check_workflow_agent_safety as mod
from scripts.check_workflow_agent_safety import check_workflow_agent_safety

_MASKED_NO_GUARD = """\
name: x
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - name: Run ci-rca agent
        run: |
          claude -p --output-format json --allowedTools "Read" "do the thing" > /tmp/out.json 2>&1 || true
          cat /tmp/out.json
"""

_MASKED_WITH_GUARD = """\
name: x
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - name: Run ci-rca agent
        run: |
          printf '%s' "$PROMPT" | claude -p --allowedTools "Read" > /tmp/out.json 2>&1 || true
          cat /tmp/out.json
          if ! grep -qE 'rec-[0-9]+' /tmp/out.json; then
            echo "::error::no rec filed"
            exit 1
          fi
"""

_UNMASKED = """\
name: x
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - name: Run agent
        run: |
          claude -p "do the thing" > /tmp/out.json
          cat /tmp/out.json
"""

_CONTINUE_ON_ERROR_NO_GUARD = """\
name: x
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - name: Run agent
        continue-on-error: true
        run: |
          claude --print "do the thing" > /tmp/out.json
"""

_NO_CLAUDE = """\
name: x
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - name: build
        run: |
          echo hi || true
"""

_USES_ACTION = """\
name: x
on: [push]
jobs:
  j:
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          claude_code_oauth_token: ${{ secrets.TOK }}
"""

_NOT_A_MAPPING = "- just\n- a\n- list\n"

_BAD_YAML = "name: x\n  bad: : indent\n:::\n"


def _write(tmp_path: Path, name: str, content: str) -> None:
    wf = tmp_path / name
    wf.write_text(content, encoding="utf-8")


@pytest.fixture
def workflows_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(mod, "WORKFLOWS_DIR", tmp_path)
    return tmp_path


def test_masked_without_guard_is_violation(workflows_dir: Path) -> None:
    _write(workflows_dir, "ci-rca.yml", _MASKED_NO_GUARD)
    violations = check_workflow_agent_safety()
    assert len(violations) == 1
    assert "ci-rca.yml" in violations[0]
    assert "Run ci-rca agent" in violations[0]


def test_masked_with_guard_passes(workflows_dir: Path) -> None:
    _write(workflows_dir, "ci-rca.yml", _MASKED_WITH_GUARD)
    assert check_workflow_agent_safety() == []


def test_unmasked_passes(workflows_dir: Path) -> None:
    _write(workflows_dir, "wf.yml", _UNMASKED)
    assert check_workflow_agent_safety() == []


def test_continue_on_error_without_guard_is_violation(workflows_dir: Path) -> None:
    _write(workflows_dir, "wf.yml", _CONTINUE_ON_ERROR_NO_GUARD)
    violations = check_workflow_agent_safety()
    assert len(violations) == 1
    assert "wf.yml" in violations[0]


def test_no_claude_invocation_passes(workflows_dir: Path) -> None:
    _write(workflows_dir, "wf.yml", _NO_CLAUDE)
    assert check_workflow_agent_safety() == []


def test_uses_action_is_ignored(workflows_dir: Path) -> None:
    _write(workflows_dir, "claude.yml", _USES_ACTION)
    assert check_workflow_agent_safety() == []


def test_non_mapping_workflow_is_skipped(workflows_dir: Path) -> None:
    _write(workflows_dir, "weird.yml", _NOT_A_MAPPING)
    assert check_workflow_agent_safety() == []


def test_bad_yaml_reports_parse_error(workflows_dir: Path) -> None:
    _write(workflows_dir, "broken.yml", _BAD_YAML)
    violations = check_workflow_agent_safety()
    assert len(violations) == 1
    assert "broken.yml" in violations[0]
    assert "YAML parse error" in violations[0]


def test_missing_workflows_dir_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "WORKFLOWS_DIR", tmp_path / "does-not-exist")
    assert check_workflow_agent_safety() == []


def test_real_workflows_pass() -> None:
    """The live .github/workflows must already satisfy the rule (both raw claude -p sites)."""
    assert check_workflow_agent_safety() == []
