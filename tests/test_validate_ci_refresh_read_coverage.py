"""Tests for the CI refresh-read resource coverage gate (rec-2702 anti-recurrence,
PLAN-ci-apply-grant-coupling), flat tests/ convention (cf. tests/test_validate_authority_budget.py).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.validate import validate_ci_refresh_read_coverage

_BOOTSTRAP_TF = """
resource "aws_iam_role_policy" "github_ci_apply" {{
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [
      {{
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        Resource = [
          "arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"
        ]
      }},
      {{
        Sid    = "SecretsManagerKnownRead"
        Effect = "Allow"
        Action = ["secretsmanager:Describe*", "secretsmanager:Get*"]
        Resource = [
          "arn:aws:secretsmanager:eu-west-2:1234567890:secret:agent-platform-known-secret-*"
        ]
      }},
      {{
        Sid    = "EventBridgeRead"
        Effect = "Allow"
        Action = ["events:Describe*", "events:List*"]
        Resource = [
          "arn:aws:events:eu-west-2:1234567890:rule/agent-platform-known-rule"
        ]
      }}
      {extra_statements}
    ]
  }})
}}
"""

_OIDC_TF = """
data "aws_iam_policy_document" "ci_ssm_refresh_read" {{
  statement {{
    sid       = "SSMParameterRead"
    effect    = "Allow"
    actions   = ["ssm:Get*"]
    resources = ["arn:aws:ssm:eu-west-2:1234567890:parameter/agent-platform/*"]
  }}
}}

data "aws_iam_policy_document" "ci_full_refresh_read" {{
  source_policy_documents = [data.aws_iam_policy_document.ci_ssm_refresh_read.json]

  statement {{
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*", "lambda:List*"]
    resources = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
  }}

  statement {{
    sid       = "SecretsManagerKnownRead"
    effect    = "Allow"
    actions   = ["secretsmanager:Describe*", "secretsmanager:Get*"]
    resources = ["arn:aws:secretsmanager:eu-west-2:1234567890:secret:agent-platform-known-secret-*"]
  }}

  statement {{
    sid       = "EventBridgeRead"
    effect    = "Allow"
    actions   = ["events:Describe*", "events:List*"]
    resources = ["arn:aws:events:eu-west-2:1234567890:rule/agent-platform-known-rule"]
  }}
  {extra_statements}
}}

resource "aws_iam_role_policy" "github_ci_plan" {{
  name   = "test-plan"
  role   = "test-plan-role"
  policy = data.aws_iam_policy_document.github_ci_plan.json
}}

data "aws_iam_policy_document" "github_ci_plan" {{
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}}

resource "aws_iam_role_policy" "github_ci_drift" {{
  name   = "test-drift"
  role   = "test-drift-role"
  policy = data.aws_iam_policy_document.github_ci_drift.json
}}

data "aws_iam_policy_document" "github_ci_drift" {{
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}}
"""

_RESOURCES_TF = """
resource "aws_lambda_function" "known_fn" {{
  function_name = "agent-platform-known-fn"
}}

resource "aws_secretsmanager_secret" "known_secret" {{
  name = "agent-platform-known-secret"
}}

resource "aws_cloudwatch_event_rule" "known_rule" {{
  name = "agent-platform-known-rule"
}}
{extra_resources}
"""


def _write_fixture(
    tmp_path: Path,
    bootstrap_extra_statements: str = "",
    oidc_extra_statements: str = "",
    extra_resources: str = "",
) -> None:
    bootstrap_dir = tmp_path / "terraform" / "bootstrap"
    bootstrap_dir.mkdir(parents=True, exist_ok=True)
    (bootstrap_dir / "github_ci_apply.tf").write_text(
        _BOOTSTRAP_TF.format(extra_statements=bootstrap_extra_statements), encoding="utf-8"
    )

    personal_dir = tmp_path / "terraform" / "personal"
    personal_dir.mkdir(parents=True, exist_ok=True)
    (personal_dir / "oidc.tf").write_text(_OIDC_TF.format(extra_statements=oidc_extra_statements), encoding="utf-8")
    (personal_dir / "resources.tf").write_text(_RESOURCES_TF.format(extra_resources=extra_resources), encoding="utf-8")


class TestValidateCiRefreshReadCoverage:
    """Tests for validate_ci_refresh_read_coverage() (rec-2702 anti-recurrence)."""

    def test_real_tree_passes(self) -> None:
        """The real repo tree, post Phase 1+2 grant broadening: zero coverage gaps across all
        three plan-capable role policies (apply, plan, drift)."""
        failed: list[str] = []
        validate_ci_refresh_read_coverage(failed)
        assert failed == []

    def test_synthetic_fully_covered_tree_passes(self, tmp_path: Path) -> None:
        """Sanity check on the test harness itself: a minimal, fully-covered synthetic module
        produces zero findings (isolates 'gap' assertions below from fixture bugs)."""
        _write_fixture(tmp_path)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert failed == []

    def test_uncovered_lambda_function_and_secret_fail_with_precise_message(self, tmp_path: Path) -> None:
        """An aws_lambda_function and an aws_secretsmanager_secret with no matching grant in any
        of the three role policies FAIL, naming the resource, its resolved name, and the role."""
        _write_fixture(
            tmp_path,
            extra_resources="""
resource "aws_lambda_function" "gap_fn" {
  function_name = "agent-platform-gap-fn"
}

resource "aws_secretsmanager_secret" "gap_secret" {
  name = "agent-platform-gap-secret"
}
""",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)

        # Each gap resource must be flagged against all three roles (apply, plan, drift).
        fn_findings = [f for f in failed if "gap_fn" in f]
        secret_findings = [f for f in failed if "gap_secret" in f]
        assert len(fn_findings) == 3, fn_findings
        assert len(secret_findings) == 3, secret_findings
        for f in fn_findings:
            assert "aws_lambda_function" in f
            assert "agent-platform-gap-fn" in f
            assert "is not refresh-read-covered" in f
        for f in secret_findings:
            assert "aws_secretsmanager_secret" in f
            assert "agent-platform-gap-secret" in f
            assert "is not refresh-read-covered" in f
        # No false positives on the resources that ARE covered.
        assert not any("known_fn" in f or "known_secret" in f or "known_rule" in f for f in failed)

    def test_unmapped_resource_type_fails_loud(self, tmp_path: Path) -> None:
        """A resource type absent from every coverage-map category (CHECKED_TYPES,
        ENUMERATED_IAM_TYPES, TRANSITIVE_TYPES, NON_AWS_TYPES, NO_GRANT_TYPES) fails loud rather
        than silently passing (Decision 55)."""
        _write_fixture(
            tmp_path,
            extra_resources="""
resource "aws_kms_key" "unmapped" {
  description = "not classified by the coverage map"
}
""",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        unmapped_findings = [f for f in failed if "unmapped resource type" in f]
        assert len(unmapped_findings) == 1, failed
        assert "aws_kms_key" in unmapped_findings[0]
        assert "unmapped" in unmapped_findings[0]
