from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.checks.roadmap.validate_plan_documents import validate_plan_documents


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


def _validate(tmp_path: Path, data: dict, capsys) -> tuple[list[str], str]:
    path = tmp_path / "PLAN-obligation-fixture.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    failed: list[str] = []
    validate_plan_documents(failed, plans_dir=tmp_path)
    return failed, capsys.readouterr().out


def test_behavior_scope_without_obligation_fails_with_plan_and_source(tmp_path: Path, capsys) -> None:
    failed, output = _validate(tmp_path, _plan(), capsys)
    assert failed == ["Plan document schema validation"]
    assert "PLAN-obligation-fixture.yaml" in output
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


def test_explicit_substantive_waiver_passes(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["test_obligation_waiver_reason"] = "No executable runtime behavior changes in this configuration-only plan."
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


def test_test_and_instruction_scope_needs_no_obligation(tmp_path: Path, capsys) -> None:
    data = _plan()
    data["scope"] = [
        {"file": "tests/test_example.py", "action": "Create", "purpose": "Add coverage."},
        {"file": ".claude/skills/planning/SKILL.md", "action": "Modify", "purpose": "Update instructions."},
    ]
    failed, _ = _validate(tmp_path, data, capsys)
    assert failed == []


@pytest.mark.parametrize(
    "source",
    ["config/settings.json", "config/tool.ini", "terraform/main.tf", "bin/runner", "Dockerfile", "Makefile"],
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
    path = tmp_path / "PLAN-obligation-fixture.yaml"
    path.write_text(yaml.safe_dump(_plan(), sort_keys=False), encoding="utf-8")
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
