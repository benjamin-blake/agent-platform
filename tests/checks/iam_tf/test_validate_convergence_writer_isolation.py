"""Tests for scripts/checks/iam_tf/validate_convergence_writer_isolation.py (T2.49 / DEP-12
hardening item 1, Decision 92 pt2). Positive fixture (conditioned convergence-write passes) plus
the load-bearing NEGATIVES that grep-presence cannot catch: a SECOND unconditioned Allow, a
conditioned-but-wrong-session-key Allow, and a missing branch DenyConvergenceRecordWrite."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_convergence_writer_isolation import validate_convergence_writer_isolation

_GOOD_CONVERGENCE_STATEMENT = """
  statement {
    sid     = "ConvergenceRecordWrite"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
    condition {
      test     = "StringLike"
      variable = "aws:userid"
      values   = ["*:${local.convergence_writer_session_name}"]
    }
  }
"""

_OIDC_TF_TMPL = """
data "aws_iam_policy_document" "github_ci_branch" {{
  statement {{
    sid    = "S3ReadWrite"
    effect = "Allow"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${{aws_s3_bucket.data_lake.arn}}/*"]
  }}
{branch_deny_statement}
}}

resource "aws_iam_role_policy" "github_ci_branch" {{
  name   = "test-branch"
  role   = "test-branch-role"
  policy = data.aws_iam_policy_document.github_ci_branch.json
}}

data "aws_iam_policy_document" "github_ci_pr" {{
{pr_statements}
}}

resource "aws_iam_role_policy" "github_ci_pr" {{
  name   = "test-pr"
  role   = "test-pr-role"
  policy = data.aws_iam_policy_document.github_ci_pr.json
}}

data "aws_iam_policy_document" "github_ci_planner" {{
{planner_statements}
}}

resource "aws_iam_role_policy" "github_ci_planner" {{
  name   = "test-planner"
  role   = "test-planner-role"
  policy = data.aws_iam_policy_document.github_ci_planner.json
}}
"""

_DEFAULT_BRANCH_DENY = """
  statement {
    sid    = "DenyConvergenceRecordWrite"
    effect = "Deny"
    actions = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }
"""

_DEFAULT_PR_STATEMENTS = """
  statement {
    sid       = "S3ReadConvergenceRecord"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }
"""


def _write_oidc_fixture(
    tmp_path: Path,
    planner_statements: str = _GOOD_CONVERGENCE_STATEMENT,
    branch_deny_statement: str = _DEFAULT_BRANCH_DENY,
    pr_statements: str = _DEFAULT_PR_STATEMENTS,
) -> None:
    personal_dir = tmp_path / "terraform" / "personal"
    personal_dir.mkdir(parents=True, exist_ok=True)
    (personal_dir / "oidc.tf").write_text(
        _OIDC_TF_TMPL.format(
            planner_statements=planner_statements,
            branch_deny_statement=branch_deny_statement,
            pr_statements=pr_statements,
        ),
        encoding="utf-8",
    )


class TestValidateConvergenceWriterIsolation:
    def test_real_tree_passes(self) -> None:
        """The real repo tree: the planner's ConvergenceRecordWrite is aws:userid-conditioned,
        github_ci_branch retains its Deny, and github_ci_pr stays read-only."""
        failed: list[str] = []
        validate_convergence_writer_isolation(failed)
        assert failed == []

    def test_synthetic_conditioned_fixture_passes(self, tmp_path: Path) -> None:
        """Sanity check on the test harness itself: the well-formed synthetic fixture produces
        zero findings (isolates the negative-fixture assertions below from fixture bugs)."""
        _write_oidc_fixture(tmp_path)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert failed == []

    def test_second_unconditioned_allow_fails(self, tmp_path: Path) -> None:
        """LOAD-BEARING NEGATIVE (the blind spot grep-presence cannot see): a SECOND,
        UNCONDITIONED s3:PutObject Allow on convergence/personal/* added alongside the correct,
        conditioned one -- a grep for 'ConvergenceRecordWrite' or 'aws:userid' still finds a hit
        and would pass; the semantic check must FAIL because the second Allow has no condition."""
        second_unconditioned = (
            _GOOD_CONVERGENCE_STATEMENT
            + """
  statement {
    sid       = "ConvergenceRecordWriteBackdoor"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }
"""
        )
        _write_oidc_fixture(tmp_path, planner_statements=second_unconditioned)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "NOT aws:userid-conditioned" in failed[0]
        assert "ConvergenceRecordWriteBackdoor" in failed[0]

    def test_wrong_session_key_condition_fails(self, tmp_path: Path) -> None:
        """LOAD-BEARING NEGATIVE: the convergence-write Allow carries a condition, but keyed to
        the WRONG session value (not local.convergence_writer_session_name) -- grep for
        'aws:userid' alone would pass; the semantic check must FAIL because the condition does
        not reference the reserved-session local."""
        wrong_key = """
  statement {
    sid     = "ConvergenceRecordWrite"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
    condition {
      test     = "StringLike"
      variable = "aws:userid"
      values   = ["*:some-other-session-name"]
    }
  }
"""
        _write_oidc_fixture(tmp_path, planner_statements=wrong_key)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "NOT aws:userid-conditioned" in failed[0]
        assert "ConvergenceRecordWrite" in failed[0]

    def test_wrong_condition_variable_fails(self, tmp_path: Path) -> None:
        """LOAD-BEARING NEGATIVE: the condition is present and references the reserved-session
        local, but keyed on the WRONG variable (not aws:userid) -- must still FAIL, since the
        wrong condition key does not actually gate the caller's identity."""
        wrong_variable = """
  statement {
    sid     = "ConvergenceRecordWrite"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
    condition {
      test     = "StringLike"
      variable = "aws:PrincipalTag/session"
      values   = ["*:${local.convergence_writer_session_name}"]
    }
  }
"""
        _write_oidc_fixture(tmp_path, planner_statements=wrong_variable)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "NOT aws:userid-conditioned" in failed[0]

    def test_no_convergence_write_at_all_fails(self, tmp_path: Path) -> None:
        """The planner grants NO s3:PutObject on convergence/personal/* -- fails (distinct from
        the unconditioned/wrong-key cases: this is the absent-grant branch)."""
        _write_oidc_fixture(tmp_path, planner_statements="")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "grants NO s3:PutObject Allow" in failed[0]

    def test_missing_branch_deny_fails(self, tmp_path: Path) -> None:
        """LOAD-BEARING NEGATIVE: github_ci_branch's explicit DenyConvergenceRecordWrite is
        removed -- the planner's own isolation is fine, but the branch-role invariant (c)
        regresses and must FAIL independently."""
        _write_oidc_fixture(tmp_path, branch_deny_statement="")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "missing its DenyConvergenceRecordWrite" in failed[0]

    def test_pr_role_convergence_write_fails(self, tmp_path: Path) -> None:
        """LOAD-BEARING NEGATIVE: github_ci_pr somehow gains a PutObject grant on
        convergence/personal/* -- must FAIL independently of the planner/branch checks."""
        pr_with_write = (
            _DEFAULT_PR_STATEMENTS
            + """
  statement {
    sid       = "AccidentalPrConvergenceWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }
"""
        )
        _write_oidc_fixture(tmp_path, pr_statements=pr_with_write)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "github_ci_pr grants s3:PutObject Allow" in failed[0]
        assert "AccidentalPrConvergenceWrite" in failed[0]

    def test_multiple_conditioned_allows_fails(self, tmp_path: Path) -> None:
        """Two SEPARATE, correctly-conditioned convergence-write Allows -- each individually
        well-formed, but the design calls for exactly one; must FAIL to keep the audit surface
        minimal (distinct code path from the unconditioned-second-Allow negative above)."""
        two_conditioned = (
            _GOOD_CONVERGENCE_STATEMENT
            + """
  statement {
    sid     = "ConvergenceRecordWriteSecond"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
    condition {
      test     = "StringLike"
      variable = "aws:userid"
      values   = ["*:${local.convergence_writer_session_name}"]
    }
  }
"""
        )
        _write_oidc_fixture(tmp_path, planner_statements=two_conditioned)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1, failed
        assert "expected exactly 1" in failed[0]

    def test_missing_oidc_file_fails_loud(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1
        assert "cannot read" in failed[0]

    def test_empty_oidc_file_fails_loud(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "oidc.tf").write_text("# nothing here\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        assert len(failed) == 1
        assert "no aws_iam_policy_document / aws_iam_role_policy blocks found" in failed[0]

    def test_missing_planner_role_fails_loud(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "oidc.tf").write_text(
            """
data "aws_iam_policy_document" "github_ci_branch" {
  statement {
    sid    = "DenyConvergenceRecordWrite"
    effect = "Deny"
    actions = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data_lake.arn}/convergence/personal/*"]
  }
}

resource "aws_iam_role_policy" "github_ci_branch" {
  name   = "test-branch"
  role   = "test-branch-role"
  policy = data.aws_iam_policy_document.github_ci_branch.json
}
""",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        planner_findings = [f for f in failed if "github_ci_planner" in f]
        assert len(planner_findings) == 1, failed
        assert "could not resolve github_ci_planner" in planner_findings[0]

    def test_missing_branch_role_fails_loud(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "oidc.tf").write_text(
            f"""
data "aws_iam_policy_document" "github_ci_planner" {{
{_GOOD_CONVERGENCE_STATEMENT}
}}

resource "aws_iam_role_policy" "github_ci_planner" {{
  name   = "test-planner"
  role   = "test-planner-role"
  policy = data.aws_iam_policy_document.github_ci_planner.json
}}
""",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        branch_findings = [f for f in failed if "github_ci_branch" in f]
        assert len(branch_findings) == 1, failed
        assert "could not resolve github_ci_branch" in branch_findings[0]

    def test_missing_pr_role_fails_loud(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "oidc.tf").write_text(
            f"""
data "aws_iam_policy_document" "github_ci_branch" {{
{_DEFAULT_BRANCH_DENY}
}}

resource "aws_iam_role_policy" "github_ci_branch" {{
  name   = "test-branch"
  role   = "test-branch-role"
  policy = data.aws_iam_policy_document.github_ci_branch.json
}}

data "aws_iam_policy_document" "github_ci_planner" {{
{_GOOD_CONVERGENCE_STATEMENT}
}}

resource "aws_iam_role_policy" "github_ci_planner" {{
  name   = "test-planner"
  role   = "test-planner-role"
  policy = data.aws_iam_policy_document.github_ci_planner.json
}}
""",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_convergence_writer_isolation(failed)
        pr_findings = [f for f in failed if "github_ci_pr" in f]
        assert len(pr_findings) == 1, failed
        assert "could not resolve github_ci_pr" in pr_findings[0]
