"""Tests for the validate_authority_budget drift gate (T2.25 / T2.48 / Decision 144 v2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_authority_budget import validate_authority_budget

# A synthetic github_ci_apply.tf that satisfies a valid v2 budget: boundary name, the
# role/agent-platform-* prefix Resource, the DenySelfInlinePolicyWrite carve-out, and the apply-role ARN.
_SYNTH_HCL = """
resource "aws_iam_policy" "github_ci_apply_boundary" {
  name = "agent-platform-github-ci-apply-boundary"
}
# IAMRoleWriteBounded Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
# DenySelfInlinePolicyWrite Resource = ["arn:aws:iam::1234567890:role/agent-platform-github-ci-apply"]
"""

_V2_BUDGET = {
    "schema_version": 2,
    "boundary_policy_name": "agent-platform-github-ci-apply-boundary",
    "in_budget_managed_role_prefix": "agent-platform-",
    "apply_role_self_exclusion": "agent-platform-github-ci-apply",
    "in_budget_resource_types": ["aws_iam_role_policy", "aws_iam_role_policy_attachment"],
    "in_budget_actions": ["create", "update"],
}


def _run_with(tmp_path: Path, budget: dict, hcl: str = _SYNTH_HCL) -> list[str]:
    bootstrap = tmp_path / "terraform" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    (bootstrap / "github_ci_apply.tf").write_text(hcl, encoding="utf-8")
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(json.dumps(budget), encoding="utf-8")
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path), patch.dict("os.environ", {"TF_AUTHORITY_BUDGET": str(budget_path)}):
        validate_authority_budget(failed)
    return failed


def test_real_budget_agrees_with_hcl() -> None:
    """The committed authority_budget.json (v2) must agree with github_ci_apply.tf (no drift)."""
    failed: list[str] = []
    validate_authority_budget(failed)
    assert failed == [], f"authority-budget drift: {failed}"


def test_v2_valid_synthetic_passes(tmp_path: Path) -> None:
    assert _run_with(tmp_path, _V2_BUDGET) == []


def test_v2_prefix_not_mapped_to_hcl_fails(tmp_path: Path) -> None:
    hcl = _SYNTH_HCL.replace("role/agent-platform-*", "role/some-other-prefix-*")
    failed = _run_with(tmp_path, _V2_BUDGET, hcl=hcl)
    assert any("does not map to" in f and "agent-platform-" in f for f in failed)


def test_v2_missing_self_exclusion_fails(tmp_path: Path) -> None:
    hcl = _SYNTH_HCL.replace("DenySelfInlinePolicyWrite", "SomethingElse")
    failed = _run_with(tmp_path, _V2_BUDGET, hcl=hcl)
    assert any("DenySelfInlinePolicyWrite" in f and "self-grant break" in f for f in failed)


def test_v2_wrong_actions_fails(tmp_path: Path) -> None:
    budget = dict(_V2_BUDGET, in_budget_actions=["update"])
    failed = _run_with(tmp_path, budget)
    assert any("in_budget_actions" in f for f in failed)


def test_boundary_name_missing_fails(tmp_path: Path) -> None:
    budget = dict(_V2_BUDGET, boundary_policy_name="not-in-hcl-boundary")
    failed = _run_with(tmp_path, budget)
    assert any("boundary_policy_name" in f for f in failed)


def test_v1_fallback_enumerated_roles(tmp_path: Path) -> None:
    """A legacy v1 budget (no prefix) still validates via the enumerated-role fallback."""
    hcl = _SYNTH_HCL + '\n# "arn:aws:iam::1234567890:role/agent-platform-github-ci-branch"\n'
    budget = {
        "schema_version": 1,
        "boundary_policy_name": "agent-platform-github-ci-apply-boundary",
        "in_budget_managed_roles": ["agent-platform-github-ci-branch"],
        "in_budget_resource_types": ["aws_iam_role_policy"],
        "in_budget_actions": ["update"],
    }
    assert _run_with(tmp_path, budget, hcl=hcl) == []


def test_v1_extra_role_not_in_hcl_fails(tmp_path: Path) -> None:
    budget = {
        "schema_version": 1,
        "boundary_policy_name": "agent-platform-github-ci-apply-boundary",
        "in_budget_managed_roles": ["some-role-not-in-hcl"],
        "in_budget_resource_types": ["aws_iam_role_policy"],
        "in_budget_actions": ["update"],
    }
    failed = _run_with(tmp_path, budget)
    assert any("some-role-not-in-hcl" in f for f in failed)


def test_v1_apply_role_self_grant_fails(tmp_path: Path) -> None:
    hcl = _SYNTH_HCL + '\n# "arn:aws:iam::1234567890:role/agent-platform-github-ci-apply"\n'
    budget = {
        "schema_version": 1,
        "boundary_policy_name": "agent-platform-github-ci-apply-boundary",
        "in_budget_managed_roles": ["agent-platform-github-ci-apply"],
        "in_budget_resource_types": ["aws_iam_role_policy"],
        "in_budget_actions": ["update"],
    }
    failed = _run_with(tmp_path, budget, hcl=hcl)
    assert any("self-grant guard" in f for f in failed)


def test_unparseable_budget_fails(tmp_path: Path) -> None:
    bootstrap = tmp_path / "terraform" / "bootstrap"
    bootstrap.mkdir(parents=True, exist_ok=True)
    (bootstrap / "github_ci_apply.tf").write_text(_SYNTH_HCL, encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path), patch.dict("os.environ", {"TF_AUTHORITY_BUDGET": str(bad)}):
        validate_authority_budget(failed)
    assert any("cannot read or parse" in f for f in failed)


def test_missing_hcl_fails(tmp_path: Path) -> None:
    budget_path = tmp_path / "budget.json"
    budget_path.write_text(json.dumps(_V2_BUDGET), encoding="utf-8")
    # _common.ROOT patched to a dir with NO terraform/bootstrap/github_ci_apply.tf.
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path), patch.dict("os.environ", {"TF_AUTHORITY_BUDGET": str(budget_path)}):
        validate_authority_budget(failed)
    assert any("cannot read" in f and "github_ci_apply.tf" in f for f in failed)
