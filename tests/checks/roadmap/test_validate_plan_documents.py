from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks.roadmap import validate_plan_documents as module
from scripts.checks.roadmap.validate_plan_documents import validate_plan_documents

_FIXTURE_NAME = "PLAN-obligation-fixture.yaml"


def _plan() -> dict:
    return {
        "schema_version": 4,
        "handoff_policy": {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
        "slug": "obligation-fixture",
        "intent": "Exercise deterministic test-obligation validation.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": "docs/plans/PLAN-obligation-fixture.yaml",
        "phase": "test",
        "scope": [{"file": "scripts/example.py", "action": "Modify", "purpose": "Change behavior."}],
        "acceptance_criteria": ["The behavior is covered."],
        "verification_plan": [
            {
                "step": 1,
                "phase": "pre-deploy",
                "action": "test",
                "command": "pytest tests/test_example.py::test_behavior",
                "expected": "passes",
                "fix_if": "repair",
            }
        ],
        "execution_steps": ["Implement."],
    }


def _validate(tmp_path: Path, data: dict, capsys, added: set[str] | None = None) -> tuple[list[str], str]:
    (tmp_path / _FIXTURE_NAME).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    failed: list[str] = []
    validate_plan_documents(failed, plans_dir=tmp_path, added_plan_names=added)
    return failed, capsys.readouterr().out


def test_behavior_scope_without_obligation_fails_with_plan_and_source(tmp_path: Path, capsys) -> None:
    failed, output = _validate(tmp_path, _plan(), capsys)
    assert failed == ["Plan document schema validation"]
    assert _FIXTURE_NAME in output
    assert "scripts/example.py" in output


def test_linked_obligation_passes(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["test_obligations"] = [
        {
            "source": "scripts/example.py",
            "behavior": "changes behavior",
            "test_selector": "tests/test_example.py::test_behavior",
            "verification_step": 1,
            "red_green_expectation": "fails before the implementation and passes after it",
        }
    ]
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


def test_per_source_waiver_passes(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["test_obligations"] = [
        {
            "source": "scripts/example.py",
            "behavior": "configuration-only change with no runtime path",
            "test_selector": "tests/test_example.py::test_behavior",
            "verification_step": 1,
            "waiver_reason": "No deterministic runtime path exists for this configuration constant.",
        }
    ]
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


def test_test_and_plan_scope_needs_no_obligation(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["scope"] = [
        {"file": "tests/test_example.py", "action": "Create", "purpose": "Add coverage."},
        {"file": ".claude/skills/planning/SKILL.md", "action": "Modify", "purpose": "Update instructions."},
        {"file": "docs/plans/PLAN-other.yaml", "action": "Modify", "purpose": "Bookkeeping."},
        {"file": "scripts/gone.py", "action": "Delete", "purpose": "Retire the module."},
    ]
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


@pytest.mark.parametrize(
    "source",
    [
        "config/settings.json",
        "config/tool.ini",
        "terraform/main.tf",
        "bin/runner",
        "Dockerfile",
        "Makefile",
        "config/agent/executor/prompts/implement.prompt.md",
        ".github/prompts/scheduled/doc-freshness.md",
    ],
)
def test_behavior_capable_formats_cannot_escape(tmp_path: Path, capsys, source: str) -> None:
    data = _plan()
    data["scope"] = [{"file": source, "action": "Modify", "purpose": "Change behavior."}]
    failed, output = _validate(tmp_path, data, capsys)
    assert failed == ["Plan document schema validation"]
    assert source in output


def test_historical_schema_remains_valid_without_obligation(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["schema_version"] = 3
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


def test_non_implementation_plan_needs_no_obligation(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["plan_type"] = "REPORT-ONLY"
    data["execution_steps"] = []
    data.pop("handoff_policy")
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


def test_newly_added_plan_below_current_schema_version_is_rejected(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["schema_version"] = 3
    failed, output = _validate(tmp_path, data, capsys, added={_FIXTURE_NAME})
    assert failed == ["Plan document schema validation"]
    assert "must declare schema_version 4" in output


def test_newly_added_plan_at_current_schema_version_is_accepted(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["test_obligations"] = [
        {
            "source": "scripts/example.py",
            "behavior": "changes behavior",
            "test_selector": "tests/test_example.py::test_behavior",
            "verification_step": 1,
            "red_green_expectation": "fails before the implementation and passes after it",
        }
    ]
    failed, _ = _validate(tmp_path, data, capsys, added={_FIXTURE_NAME})
    assert failed == []


def test_added_plan_names_selects_only_new_plan_files(monkeypatch) -> None:
    monkeypatch.setattr(
        module._common,
        "get_status_aware_diff",
        lambda: [
            ("A", "docs/plans/PLAN-new.yaml"),
            ("??", "docs/plans/PLAN-untracked.yaml"),
            ("M", "docs/plans/PLAN-edited.yaml"),
            ("D", "docs/plans/PLAN-removed.yaml"),
            ("A", "docs/plans/README.md"),
            ("A", "scripts/example.py"),
        ],
    )
    assert module._added_plan_names() == {"PLAN-new.yaml", "PLAN-untracked.yaml"}


def test_canonical_plan_template_declares_the_gated_schema_version() -> None:
    """The template agents copy must not drift below the version the obligation gate binds at.

    This is the drift that made the gate inert: prose said 'schema 4', the template still emitted 3.
    """
    skill = Path(__file__).resolve().parents[3] / ".claude" / "skills" / "planning" / "SKILL.md"
    declared = re.search(r"^schema_version: (\d+)", skill.read_text(encoding="utf-8"), re.MULTILINE)
    assert declared is not None, "planning SKILL.md has no schema_version line in its plan template"
    assert int(declared.group(1)) == module._MIN_NEW_PLAN_SCHEMA_VERSION


def test_empty_directory_passes(tmp_path: Path, capsys) -> None:
    failed: list[str] = []
    validate_plan_documents(failed, plans_dir=tmp_path)
    assert failed == []
    assert "no PLAN-*.yaml" in capsys.readouterr().out


def test_schema_failure_is_reported(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["unexpected"] = True
    failed, output = _validate(tmp_path, data, capsys)
    assert failed == ["Plan document schema validation"]
    assert "unexpected" in output


def test_import_failure_is_reported_and_sys_path_restored(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / _FIXTURE_NAME).write_text(yaml.safe_dump(_plan(), sort_keys=False), encoding="utf-8")
    root_str = str(Path(__file__).resolve().parents[3])
    monkeypatch.setattr("scripts.checks.roadmap.validate_plan_documents._common.ROOT", Path(root_str))
    monkeypatch.setattr(
        "scripts.checks.roadmap.validate_plan_documents.sys.path", [p for p in __import__("sys").path if p != root_str]
    )
    original_import = __import__

    def fail_import(name: str, *args: object, **kwargs: object):
        if name == "scripts.roadmap.plan_document":
            raise ImportError("simulated")
        return original_import(name, *args, **kwargs)

    failed: list[str] = []
    with patch("builtins.__import__", fail_import):
        validate_plan_documents(failed, plans_dir=tmp_path)
    assert failed == ["Plan document schema validation"]
    assert root_str not in __import__("sys").path
    assert "simulated" in capsys.readouterr().out
