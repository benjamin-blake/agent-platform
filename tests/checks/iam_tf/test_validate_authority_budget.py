"""Tests for the validate_authority_budget drift gate in scripts/validate.py (T2.25)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.checks.iam_tf.validate_authority_budget import validate_authority_budget


def test_real_budget_agrees_with_hcl() -> None:
    """The committed authority_budget.json must agree with github_ci_apply.tf (no drift)."""
    failed: list[str] = []
    validate_authority_budget(failed)
    assert failed == [], f"authority-budget drift: {failed}"


def test_extra_managed_role_not_in_hcl_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A budget table that lists a role absent from the IAMRoleWriteBounded SCP is rejected."""
    real_budget = Path(__file__).parent.parent.parent.parent / "terraform" / "bootstrap" / "authority_budget.json"
    budget = json.loads(real_budget.read_text(encoding="utf-8"))
    budget["in_budget_managed_roles"].append("some-role-not-in-hcl")
    bad_path = tmp_path / "bad_budget.json"
    bad_path.write_text(json.dumps(budget), encoding="utf-8")
    monkeypatch.setenv("TF_AUTHORITY_BUDGET", str(bad_path))
    failed: list[str] = []
    validate_authority_budget(failed)
    assert any("authority-budget" in f for f in failed)
    assert any("some-role-not-in-hcl" in f for f in failed)
