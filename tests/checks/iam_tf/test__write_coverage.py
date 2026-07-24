"""Tests for the write-coverage submodule (Decision 128 decomposition + Decision 144 c5, DEP-01).

Mirror of scripts/checks/iam_tf/_write_coverage.py. Covers the WRITE_COVERAGE map, _write_grant_present,
check_write_coverage's two loud-fail directions (missing write grant; apply-written type with no
WRITE_COVERAGE entry), and check_passrole_implies_coverage's rec-2831 anti-recurrence assertion
(T2.48 c1, PLAN-t248-passrole-liveproof): CreateFunction-implies-PassRole across BOTH the identity
policy (via passed apply_statements) and the boundary DataPlaneAllow ceiling (self-contained re-read
of terraform/bootstrap/github_ci_apply.tf, isolated here via monkeypatching scripts.checks._common.ROOT
to a synthetic tmp_path tree -- mirrors the tests/checks/iam_tf/validate_ci_refresh_read_coverage/
convention)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.checks import _common
from scripts.checks.iam_tf._write_coverage import (
    APPLY_WRITTEN_TYPES,
    WRITE_COVERAGE,
    _create_function_granted,
    _parse_boundary_dataplane_statement,
    _passrole_present,
    _write_grant_present,
    check_passrole_implies_coverage,
    check_write_coverage,
)


def _stmt(actions: list[str], resources_raw: str) -> dict:
    return {"sid": None, "actions": actions, "resources_raw": resources_raw}


_PASSROLE_STMT = _stmt(["iam:PassRole"], '["arn:aws:iam::1234567890:role/agent-platform-*"]')


def _fully_covered_apply_statements() -> list[dict]:
    """A synthetic apply policy that write-covers every WRITE_COVERAGE type, INCLUDING the
    rec-2831 PassRole pairing for lambda:CreateFunction (identity-side)."""
    return [
        _stmt(
            ["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"],
            '["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"]',
        ),
        _stmt(
            ["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
            '["arn:aws:logs:eu-west-2:1234567890:log-group:/aws/lambda/agent-platform-*"]',
        ),
        _stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:cloudwatch:eu-west-2:1234567890:alarm:agent-platform-*"]'),
        _stmt(["events:PutRule"], '["arn:aws:events:eu-west-2:1234567890:rule/agent-platform-*"]'),
        _stmt(["iam:CreateRole"], '["arn:aws:iam::1234567890:role/agent-platform-*"]'),
        _PASSROLE_STMT,
    ]


# ---------------------------------------------------------------------------
# Synthetic bootstrap HCL fixtures for check_passrole_implies_coverage's self-contained boundary
# re-read (scripts.checks._common.ROOT is monkeypatched to a tmp_path tree holding one of these
# under terraform/bootstrap/github_ci_apply.tf) -- mirrors the real file's shape: an identity
# aws_iam_role_policy block (carrying the PassedToService condition) plus a separate
# aws_iam_policy "github_ci_apply_boundary" block (the ceiling, unconditioned).
# ---------------------------------------------------------------------------

_IDENTITY_WITH_CONDITION = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAMPassRoleForLambda"
        Effect = "Allow"
        Action = ["iam:PassRole"]
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

_IDENTITY_WITHOUT_CONDITION = """
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
      }
    ]
  })
}
"""

_BOUNDARY_WITH_PASSROLE = """
resource "aws_iam_policy" "github_ci_apply_boundary" {
  name = "test-apply-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DataPlaneAllow"
        Effect   = "Allow"
        Action   = ["lambda:*", "iam:CreateRole", "iam:PassRole"]
        Resource = ["*"]
      },
      {
        Sid    = "DenyIAMEscalation"
        Effect = "Deny"
        Action = ["iam:CreateRole"]
        Resource = ["*"]
      }
    ]
  })
}
"""

_BOUNDARY_WITHOUT_PASSROLE = """
resource "aws_iam_policy" "github_ci_apply_boundary" {
  name = "test-apply-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DataPlaneAllow"
        Effect   = "Allow"
        Action   = ["lambda:*", "iam:CreateRole"]
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


class TestWriteCoverageMap:
    def test_apply_written_types_all_mapped(self) -> None:
        # Every declared apply-written type has a WRITE_COVERAGE entry (structural invariant).
        assert APPLY_WRITTEN_TYPES <= set(WRITE_COVERAGE)

    def test_every_entry_has_actions_and_marker(self) -> None:
        for rtype, spec in WRITE_COVERAGE.items():
            assert spec["write_actions"], rtype
            assert spec["resource_marker"], rtype


class TestWriteGrantPresent:
    def test_present_when_all_actions_on_marker(self) -> None:
        stmts = _fully_covered_apply_statements()
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_lambda_function"]) is True

    def test_absent_when_action_missing(self) -> None:
        # Only CreateFunction granted; UpdateFunctionConfiguration missing -> not covered.
        stmts = [_stmt(["lambda:CreateFunction"], '["...function:agent-platform-*"]')]
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_lambda_function"]) is False

    def test_absent_when_marker_missing(self) -> None:
        # Right actions, wrong resource (no marker) -> not covered.
        stmts = [_stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:cloudwatch:...:alarm:something-else-*"]')]
        # marker "alarm:" IS a substring of the resource, so this one is covered -- use a resource
        # with no "alarm:" token to prove the negative branch.
        stmts_no_marker = [_stmt(["cloudwatch:PutMetricAlarm"], '["arn:aws:sns:...:agent-platform-alerts"]')]
        assert _write_grant_present(stmts_no_marker, WRITE_COVERAGE["aws_cloudwatch_metric_alarm"]) is False
        assert _write_grant_present(stmts, WRITE_COVERAGE["aws_cloudwatch_metric_alarm"]) is True


class TestCheckWriteCoverage:
    def test_fully_covered_no_findings(self) -> None:
        failed: list[str] = []
        n = check_write_coverage(_fully_covered_apply_statements(), [], failed, "k:")
        assert failed == []
        assert n == len(WRITE_COVERAGE)

    def test_missing_write_grant_fails_loud(self) -> None:
        # Drop the lambda grant -> aws_lambda_function is not write-covered.
        stmts = [s for s in _fully_covered_apply_statements() if "lambda:CreateFunction" not in s["actions"]]
        failed: list[str] = []
        check_write_coverage(stmts, [], failed, "k:")
        assert any("aws_lambda_function" in f and "no covering write grant" in f for f in failed)
        assert all(f.startswith("k:") for f in failed)

    def test_unmapped_apply_written_type_fails_loud(self, monkeypatch) -> None:
        # Simulate a new apply-written type declared without a WRITE_COVERAGE entry.
        import scripts.checks.iam_tf._write_coverage as wc

        monkeypatch.setattr(wc, "APPLY_WRITTEN_TYPES", frozenset(WRITE_COVERAGE) | {"aws_sfn_state_machine"})
        resources = [("aws_sfn_state_machine", "pipeline", "prod.tf")]
        failed: list[str] = []
        wc.check_write_coverage(_fully_covered_apply_statements(), resources, failed, "k:")
        assert any("aws_sfn_state_machine" in f and "no\n" not in f and "WRITE_COVERAGE entry" in f for f in failed)


class TestCreateFunctionGrantedAndPassrolePresent:
    """Unit coverage for the two small predicates check_passrole_implies_coverage composes."""

    def test_create_function_granted_true(self) -> None:
        assert _create_function_granted(_fully_covered_apply_statements()) is True

    def test_create_function_granted_false(self) -> None:
        stmts = [s for s in _fully_covered_apply_statements() if "lambda:CreateFunction" not in s["actions"]]
        assert _create_function_granted(stmts) is False

    def test_passrole_present_true(self) -> None:
        assert _passrole_present([_PASSROLE_STMT]) is True

    def test_passrole_present_false_wrong_marker(self) -> None:
        wrong_marker = _stmt(["iam:PassRole"], '["arn:aws:iam::1234567890:role/some-other-*"]')
        assert _passrole_present([wrong_marker]) is False

    def test_passrole_present_false_absent(self) -> None:
        assert _passrole_present([]) is False


class TestParseBoundaryDataplaneStatement:
    """Unit coverage for the self-contained boundary re-read primitive."""

    def test_finds_dataplane_allow_with_passrole(self) -> None:
        text = _IDENTITY_WITH_CONDITION + _BOUNDARY_WITH_PASSROLE
        stmt = _parse_boundary_dataplane_statement(text)
        assert stmt is not None
        assert stmt["sid"] == "DataPlaneAllow"
        assert "iam:PassRole" in stmt["actions"]

    def test_finds_dataplane_allow_without_passrole(self) -> None:
        text = _IDENTITY_WITH_CONDITION + _BOUNDARY_WITHOUT_PASSROLE
        stmt = _parse_boundary_dataplane_statement(text)
        assert stmt is not None
        assert "iam:PassRole" not in stmt["actions"]

    def test_returns_none_when_boundary_resource_absent(self) -> None:
        assert _parse_boundary_dataplane_statement(_IDENTITY_WITH_CONDITION) is None


class TestCheckPassroleImpliesCoverage:
    """rec-2831 anti-recurrence (T2.48 c1): CreateFunction-implies-PassRole, identity + boundary."""

    def test_no_createfunction_short_circuits_no_file_read(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # tmp_path has NO terraform/bootstrap/github_ci_apply.tf at all -- if the function attempted
        # to read it despite CreateFunction being absent, this would fail loud (OSError branch).
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        stmts = [s for s in _fully_covered_apply_statements() if "lambda:CreateFunction" not in s["actions"]]
        failed: list[str] = []
        check_passrole_implies_coverage(stmts, failed, "k:")
        assert failed == []

    def test_positive_identity_and_boundary_and_condition_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_WITH_PASSROLE)
        failed: list[str] = []
        check_passrole_implies_coverage(_fully_covered_apply_statements(), failed, "k:")
        assert failed == []

    def test_negative_createfunction_without_identity_passrole_fails_loud(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative case 1 (VP step 4): CreateFunction granted, identity apply_statements carry NO
        PassRole grant -- fails loud even though the boundary + condition are otherwise fine."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_WITH_PASSROLE)
        stmts = [s for s in _fully_covered_apply_statements() if s is not _PASSROLE_STMT]
        failed: list[str] = []
        check_passrole_implies_coverage(stmts, failed, "k:")
        assert len(failed) == 1, failed
        assert "identity policy has no iam:PassRole grant" in failed[0]
        assert "rec-2831" in failed[0]
        assert failed[0].startswith("k:")

    def test_negative_boundary_missing_passrole_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Negative case 2 (VP step 4): identity policy grants PassRole correctly, but the boundary
        DataPlaneAllow ceiling does not -- fails loud (a grant absent from the ceiling is silently
        denied by the identity/boundary intersection)."""
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION + _BOUNDARY_WITHOUT_PASSROLE)
        failed: list[str] = []
        check_passrole_implies_coverage(_fully_covered_apply_statements(), failed, "k:")
        assert len(failed) == 1, failed
        assert "boundary" in failed[0] and "does not grant" in failed[0]
        assert "rec-2831" in failed[0]
        assert failed[0].startswith("k:")

    def test_condition_marker_missing_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Bonus coverage beyond the required 2 negative cases: identity + boundary both grant
        # PassRole, but the PassedToService=lambda.amazonaws.com condition text is absent entirely.
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITHOUT_CONDITION + _BOUNDARY_WITH_PASSROLE)
        failed: list[str] = []
        check_passrole_implies_coverage(_fully_covered_apply_statements(), failed, "k:")
        assert len(failed) == 1, failed
        assert "PassedToService" in failed[0]
        assert "Decision 143" in failed[0]

    def test_boundary_resource_entirely_absent_fails_loud(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Bonus coverage: HCL shape drift -- the boundary resource itself is gone, not just its
        # PassRole grant. Distinguishes the "not found" branch from the "found, missing grant" branch.
        monkeypatch.setattr(_common, "ROOT", tmp_path)
        _write_bootstrap(tmp_path, _IDENTITY_WITH_CONDITION)
        failed: list[str] = []
        check_passrole_implies_coverage(_fully_covered_apply_statements(), failed, "k:")
        assert len(failed) == 1, failed
        assert "could not locate the github_ci_apply_boundary DataPlaneAllow statement" in failed[0]

    def test_real_bootstrap_file_passes(self) -> None:
        # Unpatched _common.ROOT -- exercises the self-contained re-read against the ACTUAL live
        # terraform/bootstrap/github_ci_apply.tf (mirrors the validate_ci_refresh_read_coverage
        # package's test_real_tree_passes convention).
        failed: list[str] = []
        check_passrole_implies_coverage(_fully_covered_apply_statements(), failed, "k:")
        assert failed == []
