"""CD.30-safe pre-tier obligation guard.

Placement alone is not the guard: asserting only that validate_plan_documents appears in the
pre sequence stays green if the obligation logic becomes a no-op. These tests dispatch the check
the way the fast tier does -- via registry.resolve(), which the real _dispatch_check chokepoint
uses (Decision 169) -- against a fixture plan that declares behavior-changing scope with no
obligation.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from scripts.checks.registry import full_sequence, pre_sequence, resolve

_CHECK_NAME = "validate_plan_documents"


def _behavior_plan_without_obligations() -> dict:
    return {
        "schema_version": 4,
        "handoff_policy": {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
        "slug": "pre-tier-obligation-fixture",
        "intent": "Fixture plan whose behavior-changing scope declares no test obligation.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": "docs/plans/PLAN-pre-tier-obligation-fixture.yaml",
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


def _dispatch_as_pre_tier(plans_dir: Path) -> list[str]:
    """Resolve and call the check exactly as scripts/validate.py's registry.resolve() dispatch does."""
    step = next(s for s in pre_sequence() if s.name == _CHECK_NAME)
    failed: list[str] = []
    resolve(step.name)(failed, plans_dir=plans_dir, added_plan_names=set())
    return failed


def test_obligation_guard_is_reachable_in_pre_without_promoting_coverage() -> None:
    pre = [step.name for step in pre_sequence()]
    full = [step.name for step in full_sequence()]
    assert _CHECK_NAME in pre
    assert _CHECK_NAME in full
    assert "validate_test_coverage" not in pre
    assert "validate_test_coverage" in full


def test_pre_tier_dispatch_rejects_behavior_scope_without_an_obligation(tmp_path: Path, capsys) -> None:
    path = tmp_path / "PLAN-pre-tier-obligation-fixture.yaml"
    path.write_text(yaml.safe_dump(_behavior_plan_without_obligations(), sort_keys=False), encoding="utf-8")

    failed = _dispatch_as_pre_tier(tmp_path)

    assert failed == ["Plan document schema validation"]
    assert "lacks a linked test obligation" in capsys.readouterr().out


def test_pre_tier_dispatch_accepts_a_linked_obligation(tmp_path: Path, capsys) -> None:
    data = _behavior_plan_without_obligations()
    data["test_obligations"] = [
        {
            "source": "scripts/example.py",
            "behavior": "changes behavior",
            "test_selector": "tests/test_example.py::test_behavior",
            "verification_step": 1,
            "red_green_expectation": "fails before the implementation and passes after it",
        }
    ]
    path = tmp_path / "PLAN-pre-tier-obligation-fixture.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    assert _dispatch_as_pre_tier(tmp_path) == []
    capsys.readouterr()
