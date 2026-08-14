"""Split-root regression tests for _write_companions.py (PLAN-terraform-decompose-oidc-rename).

Split out of test__write_companions.py (SLOC governance, Decision 128) -- a second test file for
the same source module rather than a package conversion. Self-contained by construction (no
cross-test imports): the fixture constants below are deliberately duplicated from
test__write_companions.py rather than imported from it."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import _common
from scripts.checks.iam_tf._write_companions import check_lifecycle_companions

_ROLE_PREFIX_RESOURCE = '["arn:aws:iam::1234567890:role/agent-platform-*"]'
_INSTANCE_PROFILE_PREFIX_RESOURCE = '["arn:aws:iam::1234567890:instance-profile/agent-platform-*"]'

_IDENTITY_WITH_CONDITION = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "IAMPassRoleForLambda"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "lambda.amazonaws.com"
          }
        }
      }
    ]
  })
}
"""

_BOUNDARY_FULL = """
resource "aws_iam_policy" "github_ci_apply_boundary" {
  name = "test-apply-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DataPlaneAllow"
        Effect   = "Allow"
        Action   = [
          "lambda:*", "iam:CreateRole", "iam:PassRole", "iam:TagRole", "iam:UntagRole", "iam:UpdateRole",
          "iam:DeleteRole", "iam:ListInstanceProfilesForRole", "iam:RemoveRoleFromInstanceProfile"
        ]
        Resource = ["*"]
      }
    ]
  })
}
"""

_BOUNDARY_WITHOUT_INSTANCE_PROFILE_VERBS = """
resource "aws_iam_policy" "github_ci_apply_boundary" {
  name = "test-apply-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DataPlaneAllow"
        Effect   = "Allow"
        Action   = ["lambda:*", "iam:CreateRole", "iam:PassRole", "iam:DeleteRole"]
        Resource = ["*"]
      }
    ]
  })
}
"""


def _stmt(actions: list[str], resources_raw: str, effect: str = "Allow") -> dict:
    return {"sid": None, "actions": actions, "resources_raw": resources_raw, "effect": effect}


def _write_bootstrap_split(tmp_path: Path, identity_body: str, boundary_body: str, decoy_body: str = "") -> None:
    """The post-split shape: identity policy and boundary policy in SIBLING .tf files, plus an
    optional decoy file that must neither satisfy nor break resolution."""
    bootstrap_dir = tmp_path / "terraform" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    (bootstrap_dir / "github_ci_apply.tf").write_text("# retained role/trust only -- no policy here\n", encoding="utf-8")
    (bootstrap_dir / "github_ci_apply_policy.tf").write_text(identity_body, encoding="utf-8")
    (bootstrap_dir / "github_ci_apply_boundary.tf").write_text(boundary_body, encoding="utf-8")
    if decoy_body:
        (bootstrap_dir / "zz_decoy.tf").write_text(decoy_body, encoding="utf-8")


class TestSplitRootResolution:
    """Post-terraform-decompose-oidc-rename shape: the identity policy and the boundary policy
    live in SIBLING .tf files under terraform/bootstrap/, not one single github_ci_apply.tf. Both
    boundary re-read sites (_load_boundary_actions, _check_passrole_condition) must resolve across
    the whole root."""

    def test_boundary_ceiling_resolves_when_identity_and_boundary_are_in_sibling_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap_split(tmp_path, _IDENTITY_WITH_CONDITION, _BOUNDARY_FULL)
        stmts = [
            _stmt(
                ["iam:DeleteRole", "iam:DetachRolePolicy", "iam:DeleteRolePolicy", "iam:ListInstanceProfilesForRole"],
                _ROLE_PREFIX_RESOURCE,
            ),
            _stmt(["iam:RemoveRoleFromInstanceProfile"], _INSTANCE_PROFILE_PREFIX_RESOURCE),
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        assert failed == []

    def test_passrole_condition_resolves_when_identity_is_in_a_sibling_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap_split(tmp_path, _IDENTITY_WITH_CONDITION, _BOUNDARY_FULL)
        stmts = [
            _stmt(["lambda:CreateFunction", "lambda:TagResource"], '["...function:agent-platform-*"]'),
            _stmt(["iam:PassRole"], _ROLE_PREFIX_RESOURCE),
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        assert failed == []

    def test_decoy_sibling_file_neither_satisfies_nor_breaks_the_boundary_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A decoy file carrying an UNRELATED policy resource (different name, its own DataPlaneAllow
        -shaped Sid with a narrower Action list) must not be mistaken for the real boundary, and must
        not suppress the real boundary's own resolution."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        decoy = """
resource "aws_iam_policy" "some_other_boundary" {
  name = "unrelated-decoy-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DataPlaneAllow"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["*"]
      }
    ]
  })
}
"""
        _write_bootstrap_split(tmp_path, _IDENTITY_WITH_CONDITION, _BOUNDARY_FULL, decoy_body=decoy)
        stmts = [
            _stmt(
                ["iam:DeleteRole", "iam:DetachRolePolicy", "iam:DeleteRolePolicy", "iam:ListInstanceProfilesForRole"],
                _ROLE_PREFIX_RESOURCE,
            ),
            _stmt(["iam:RemoveRoleFromInstanceProfile"], _INSTANCE_PROFILE_PREFIX_RESOURCE),
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        assert failed == [], (
            "a decoy aws_iam_policy resource named 'some_other_boundary' must never satisfy the "
            "github_ci_apply_boundary lookup, and its own DataPlaneAllow-named Sid must not be "
            "mistaken for the real ceiling"
        )

    def test_decoy_sibling_file_does_not_manufacture_a_false_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mirror negative: a decoy carrying the companion action must NOT let a genuinely
        under-provisioned real boundary pass -- the decoy's grant must not be unioned in."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        decoy = """
resource "aws_iam_policy" "some_other_boundary" {
  name = "unrelated-decoy-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SomeOtherSid"
        Effect   = "Allow"
        Action   = ["iam:RemoveRoleFromInstanceProfile"]
        Resource = ["*"]
      }
    ]
  })
}
"""
        _write_bootstrap_split(tmp_path, _IDENTITY_WITH_CONDITION, _BOUNDARY_WITHOUT_INSTANCE_PROFILE_VERBS, decoy_body=decoy)
        stmts = [
            _stmt(["iam:DeleteRole", "iam:ListInstanceProfilesForRole"], _ROLE_PREFIX_RESOURCE),
            _stmt(["iam:RemoveRoleFromInstanceProfile"], _INSTANCE_PROFILE_PREFIX_RESOURCE),
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        assert len(failed) == 2, failed
        assert all("DataPlaneAllow ceiling does not grant it" in f for f in failed)
