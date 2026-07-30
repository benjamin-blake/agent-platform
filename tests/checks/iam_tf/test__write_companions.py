"""Tests for the MANDATORY-DECLARATION lifecycle-companion table (design (b)).

Mirror of scripts/checks/iam_tf/_write_companions.py. The load-bearing case is
TestDeleteRolePreFixRegression: it builds the PRE-FIX policy (iam:DeleteRole granted at
role/agent-platform-*, iam:ListInstanceProfilesForRole absent) and asserts the delete row FAILS --
i.e. proves the phase-keyed table would have caught rec-2882 at REVIEW time instead of in a live
gated destroy. The rest of the module covers the mandatory-declaration negatives (a WRITE_COVERAGE
type with no declaration; an empty companion tuple with no justification), the inert-row skip, the
boundary-ceiling assertion, and the facade wiring that keeps the checker out of dead-code status.

Self-contained by construction (no cross-test imports): the synthetic bootstrap HCL below is this
module's own, and scripts.checks._common.ROOT is monkeypatched to a tmp_path tree for every case
that exercises the boundary re-read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import _common
from scripts.checks.iam_tf import _write_companions as companions
from scripts.checks.iam_tf._read_coverage import (
    _BOOTSTRAP_TF_REL,
    _parse_bootstrap_statements,
    _parse_managed_policy_statements,
)
from scripts.checks.iam_tf._write_companions import (
    LIFECYCLE_COMPANIONS,
    PHASES,
    _identity_allow_iam_actions,
    check_identity_iam_actions_subset_of_boundary,
    check_lifecycle_companions,
)
from scripts.checks.iam_tf._write_coverage import WRITE_COVERAGE

_ROLE_PREFIX_RESOURCE = '["arn:aws:iam::1234567890:role/agent-platform-*"]'
_ENUMERATED_ROLES_RESOURCE = (
    '["arn:aws:iam::1234567890:role/agent-platform-github-ci-branch", '
    '"arn:aws:iam::1234567890:role/agent-platform-github-ci-pr"]'
)


def _stmt(actions: list[str], resources_raw: str, effect: str = "Allow") -> dict:
    return {"sid": None, "actions": actions, "resources_raw": resources_raw, "effect": effect}


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


def _write_bootstrap(tmp_path: Path, body: str) -> None:
    bootstrap_dir = tmp_path / "terraform" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    (bootstrap_dir / "github_ci_apply.tf").write_text(body, encoding="utf-8")


def _real_apply_statements() -> list[dict]:
    text = (_common.ROOT / _BOOTSTRAP_TF_REL).read_text(encoding="utf-8")
    inline = _parse_bootstrap_statements(text, "github_ci_apply")
    assert inline, "could not parse the real github_ci_apply policy -- has the HCL shape changed?"
    return inline + _parse_managed_policy_statements(text, "github_ci_apply_reads")


class TestTableShape:
    def test_every_write_coverage_type_declares_all_three_phases(self) -> None:
        for rtype in WRITE_COVERAGE:
            rows = LIFECYCLE_COMPANIONS.get(rtype)
            assert rows is not None, rtype
            for phase in PHASES:
                assert phase in rows, (rtype, phase)

    def test_no_row_for_a_type_outside_write_coverage(self) -> None:
        assert set(LIFECYCLE_COMPANIONS) <= set(WRITE_COVERAGE)

    def test_every_row_carries_a_justification_and_well_formed_companions(self) -> None:
        for rtype, rows in LIFECYCLE_COMPANIONS.items():
            for phase, row in rows.items():
                assert row["why"].strip(), (rtype, phase)
                for action, marker in row["companions"]:
                    assert ":" in action, (rtype, phase, action)
                    assert marker.strip(), (rtype, phase, action)

    def test_delete_role_row_names_the_rec_2882_verbs(self) -> None:
        """The row that did not exist before this plan -- named explicitly so a future edit that
        drops it fails here rather than in a live gated destroy."""
        row = LIFECYCLE_COMPANIONS["aws_iam_role"]["delete"]
        assert row["trigger"] == "iam:DeleteRole"
        assert {action for action, _ in row["companions"]} == {
            "iam:ListInstanceProfilesForRole",
            "iam:RemoveRoleFromInstanceProfile",
        }
        assert "deleteRoleInstanceProfiles()" in row["why"]


class TestDeleteRolePreFixRegression:
    """THE load-bearing case (rec-2882, instance 3 of the class): the PRE-FIX policy must FAIL."""

    def test_pre_fix_delete_role_policy_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_FULL)
        # The exact pre-fix shape: DeleteRole granted at the prefix; neither instance-profile verb
        # granted anywhere. This is what shipped, guard-PASSed, and then killed a live gated destroy.
        pre_fix = [_stmt(["iam:DeleteRole", "iam:DetachRolePolicy", "iam:DeleteRolePolicy"], _ROLE_PREFIX_RESOURCE)]
        failed: list[str] = []
        check_lifecycle_companions(pre_fix, failed, "k:")
        assert len(failed) == 2, failed
        assert any("iam:ListInstanceProfilesForRole" in f for f in failed)
        assert any("iam:RemoveRoleFromInstanceProfile" in f for f in failed)
        for f in failed:
            assert "aws_iam_role delete" in f
            assert "deleteRoleInstanceProfiles()" in f
            assert f.startswith("k:")

    def test_post_fix_delete_role_policy_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_FULL)
        post_fix = [
            _stmt(
                [
                    "iam:DeleteRole",
                    "iam:DetachRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:ListInstanceProfilesForRole",
                    "iam:RemoveRoleFromInstanceProfile",
                ],
                _ROLE_PREFIX_RESOURCE,
            )
        ]
        failed: list[str] = []
        check_lifecycle_companions(post_fix, failed, "k:")
        assert failed == []

    def test_companion_narrowed_below_the_trigger_prefix_fails_loud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The rec-2842 shape, generalized: the companion verbs are PRESENT but scoped narrower than
        the trigger's prefix -- a RESOURCE-SCOPE mismatch, not an action-absence gap."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_FULL)
        stmts = [
            _stmt(["iam:CreateRole"], _ROLE_PREFIX_RESOURCE),
            _stmt(["iam:TagRole", "iam:UntagRole"], _ENUMERATED_ROLES_RESOURCE),
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        # Exactly the create row fires (iam:UpdateRole is ungranted, so the update row is inert).
        assert len(failed) == 3, failed
        assert any("'iam:TagRole'" in f for f in failed)
        assert any("'iam:UntagRole'" in f for f in failed)
        assert any("'iam:UpdateRole'" in f for f in failed)
        assert all("narrower than 'role/agent-platform-*'" in f for f in failed)
        assert all("aws_iam_role create" in f for f in failed)


class TestMandatoryDeclaration:
    """A WRITE_COVERAGE type can no longer stay SILENT about a lifecycle phase."""

    def _row(self) -> dict:
        return companions._row("svc:CreateThing", (), "a single call")

    def test_type_with_no_declaration_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(companions, "WRITE_COVERAGE", {"aws_thing": {"write_actions": ("svc:CreateThing",)}})
        monkeypatch.setattr(companions, "LIFECYCLE_COMPANIONS", {})
        failed: list[str] = []
        check_lifecycle_companions([], failed, "k:")
        assert len(failed) == 1, failed
        assert "aws_thing" in failed[0] and "NO lifecycle-companion declaration" in failed[0]
        assert failed[0].startswith("k:")

    def test_type_missing_one_phase_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(companions, "WRITE_COVERAGE", {"aws_thing": {"write_actions": ("svc:CreateThing",)}})
        monkeypatch.setattr(
            companions,
            "LIFECYCLE_COMPANIONS",
            {"aws_thing": {"create": self._row(), "update": self._row()}},
        )
        failed: list[str] = []
        check_lifecycle_companions([], failed, "k:")
        assert len(failed) == 1, failed
        assert "declares no 'delete' lifecycle-companion row" in failed[0]

    def test_empty_companion_tuple_without_justification_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(companions, "WRITE_COVERAGE", {"aws_thing": {"write_actions": ("svc:CreateThing",)}})
        monkeypatch.setattr(
            companions,
            "LIFECYCLE_COMPANIONS",
            {
                "aws_thing": {
                    "create": self._row(),
                    "update": self._row(),
                    "delete": companions._row("svc:DeleteThing", (), "   "),
                }
            },
        )
        failed: list[str] = []
        check_lifecycle_companions([], failed, "k:")
        assert len(failed) == 1, failed
        assert "EMPTY companion tuple with no justification" in failed[0]
        assert "'delete'" in failed[0]


class TestInertRows:
    def test_ungranted_trigger_is_skipped_not_failed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An inert row imposes nothing: the pipeline cannot reach the phase, so its companions are
        not required. tmp_path holds NO bootstrap file -- if the checker tried to read the boundary
        for a skipped row, the OSError branch would fail loud and this test would catch it."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        failed: list[str] = []
        check_lifecycle_companions([_stmt(["s3:GetObject"], '["*"]')], failed, "k:")
        assert failed == []

    def test_trigger_none_row_is_inert_by_declaration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A phase that issues NO AWS call declares trigger=None -- inert by declaration rather than
        by the accident of a missing grant, so its companion tuple is never asserted."""
        monkeypatch.setattr(companions, "WRITE_COVERAGE", {"aws_thing": {"write_actions": ("svc:CreateThing",)}})
        single = companions._row("svc:CreateThing", (), "a single call")
        no_call = companions._row(None, companions._at("thing/x", "svc:TagThing"), "destroy issues no AWS call")
        monkeypatch.setattr(
            companions,
            "LIFECYCLE_COMPANIONS",
            {"aws_thing": {"create": single, "update": single, "delete": no_call}},
        )
        failed: list[str] = []
        check_lifecycle_companions([_stmt(["svc:CreateThing"], '["thing/x"]')], failed, "k:")
        assert failed == []


class TestBoundaryCeiling:
    def test_iam_companion_absent_from_boundary_fails_even_when_identity_grants_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A grant absent from the boundary DataPlaneAllow ceiling is silently denied by the
        identity/boundary intersection -- so an identity-only companion grant is NOT enough."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_WITHOUT_INSTANCE_PROFILE_VERBS)
        stmts = [
            _stmt(
                ["iam:DeleteRole", "iam:ListInstanceProfilesForRole", "iam:RemoveRoleFromInstanceProfile"],
                _ROLE_PREFIX_RESOURCE,
            )
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        assert len(failed) == 2, failed
        assert all("DataPlaneAllow ceiling does not grant it" in f for f in failed)
        assert any("iam:ListInstanceProfilesForRole" in f for f in failed)
        assert any("iam:RemoveRoleFromInstanceProfile" in f for f in failed)

    def test_missing_bootstrap_file_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        failed: list[str] = []
        check_lifecycle_companions([_stmt(["iam:DeleteRole"], _ROLE_PREFIX_RESOURCE)], failed, "k:")
        assert any("cannot re-read" in f for f in failed)

    def test_boundary_resource_absent_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION)
        failed: list[str] = []
        check_lifecycle_companions([_stmt(["iam:DeleteRole"], _ROLE_PREFIX_RESOURCE)], failed, "k:")
        assert any("could not locate the github_ci_apply_boundary DataPlaneAllow statement" in f for f in failed)


class TestPassRoleCondition:
    def test_unconditioned_passrole_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decision 143 worst-verb scoping: CreateFunction's PassRole companion must be conditioned."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        identity_without_condition = _IDENTITY_WITH_CONDITION.replace('"iam:PassedToService"', '"iam:SomethingElse"')
        _write_bootstrap(tmp_path, identity_without_condition + _BOUNDARY_FULL)
        stmts = [
            _stmt(["lambda:CreateFunction", "lambda:TagResource"], '["...function:agent-platform-*"]'),
            _stmt(["iam:PassRole"], _ROLE_PREFIX_RESOURCE),
        ]
        failed: list[str] = []
        check_lifecycle_companions(stmts, failed, "k:")
        assert len(failed) == 1, failed
        assert "PassedToService" in failed[0] and "Decision 143" in failed[0]


class TestIdentityAllowIamActions:
    def test_collects_allow_iam_actions_only(self) -> None:
        stmts = [
            _stmt(["iam:CreateRole"], _ROLE_PREFIX_RESOURCE, effect="Allow"),
            _stmt(["s3:GetObject"], '["*"]', effect="Allow"),
            _stmt(["iam:DeleteRolePolicy"], '["...self"]', effect="Deny"),
        ]
        assert _identity_allow_iam_actions(stmts) == {"iam:CreateRole"}

    def test_missing_effect_key_treated_as_allow(self) -> None:
        stmts = [{"sid": None, "actions": ["iam:CreateRole"], "resources_raw": "[...]"}]
        assert _identity_allow_iam_actions(stmts) == {"iam:CreateRole"}


class TestCheckIdentityIamActionsSubsetOfBoundary:
    """Relocated from _write_coverage with its checker (same ceiling-assertion family)."""

    def test_no_iam_actions_short_circuits_no_file_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        failed: list[str] = []
        check_identity_iam_actions_subset_of_boundary([_stmt(["s3:GetObject"], '["*"]')], failed, "k:")
        assert failed == []

    def test_all_identity_iam_actions_covered_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_FULL)
        failed: list[str] = []
        check_identity_iam_actions_subset_of_boundary([_stmt(["iam:CreateRole", "iam:PassRole"], "[...]")], failed, "k:")
        assert failed == []

    def test_identity_allow_action_absent_from_boundary_fails_loud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_WITHOUT_INSTANCE_PROFILE_VERBS)
        failed: list[str] = []
        check_identity_iam_actions_subset_of_boundary([_stmt(["iam:TagRole"], "[...]")], failed, "k:")
        assert len(failed) == 1, failed
        assert "'iam:TagRole'" in failed[0] and "does not grant it" in failed[0]

    def test_deny_only_action_absent_from_boundary_is_not_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_WITHOUT_INSTANCE_PROFILE_VERBS)
        stmts = [_stmt(["iam:TagRole"], "[...]", effect="Deny")]
        failed: list[str] = []
        check_identity_iam_actions_subset_of_boundary(stmts, failed, "k:")
        assert failed == []


class TestRealTree:
    def test_real_tree_passes_lifecycle_companions(self) -> None:
        failed: list[str] = []
        check_lifecycle_companions(_real_apply_statements(), failed, "k:")
        assert failed == []

    def test_real_tree_passes_identity_boundary_subset(self) -> None:
        failed: list[str] = []
        check_identity_iam_actions_subset_of_boundary(_real_apply_statements(), failed, "k:")
        assert failed == []


class TestFacadeWiring:
    """Anti-dead-code regression (the PR #752 REVISE lesson): a checker that is defined and
    unit-tested but never reached from the registered check is dead in the standing --pre gate."""

    def test_registered_check_calls_the_companion_checkers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from scripts.checks.iam_tf import validate_ci_refresh_read_coverage as facade

        called: list[str] = []
        monkeypatch.setattr(facade, "check_lifecycle_companions", lambda s, f, k: called.append("companions"))
        monkeypatch.setattr(
            facade, "check_identity_iam_actions_subset_of_boundary", lambda s, f, k: called.append("boundary-subset")
        )
        facade.validate_ci_refresh_read_coverage([])
        assert called == ["companions", "boundary-subset"]
