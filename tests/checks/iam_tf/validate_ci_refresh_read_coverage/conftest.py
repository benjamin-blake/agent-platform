"""Package-scoped fixtures + shared fixture-builders for the validate_ci_refresh_read_coverage
tests (Decision 131 sub-conftest).

Holds the one pytest fixture every concern-split module needs (synthetic_parity_exempt -- NOT
autouse: test_real_tree.py::test_real_tree_passes must run every production rule unmodified
against the production policy) PLUS the synthetic-bootstrap-HCL builder (_apply_policy /
_write_ci_refresh_read_fixture) that test_end_to_end.py needs. conftest modules are exempt from
the cross-test-import ban by construction (the name does not start with `test_`), which is why
these live here rather than in a concern-split module a future addition to this package would
have to avoid importing from.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.iam_tf._write_coverage import WRITE_COVERAGE

_APPLY_POLICY_HEAD = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
"""

_READ_SID_LAMBDA = """      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        Resource = [
          "arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"
        ]
      },
"""

_READ_SID_OIDC = """      {
        Sid    = "OIDCProviderRead"
        Effect = "Allow"
        Action = ["iam:GetOpenIDConnectProvider"]
        Resource = ["arn:aws:iam::1234567890:oidc-provider/token.actions.githubusercontent.com"]
      },
"""

# The WRITE half every synthetic apply policy shares. Each Sid carries its type's required write
# verbs (design (a)) AND the lifecycle companions those verbs' phases declare (design (b)), with
# every Tag* paired to its Untag* at the same scope (design (c) rule 1).
_WRITE_SIDS = """      {
        Sid    = "LambdaFunctionWrite"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction", "lambda:UpdateFunctionConfiguration",
          "lambda:TagResource", "lambda:UntagResource"
        ]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"]
      },
      {
        Sid    = "CloudWatchLogsWrite"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup", "logs:PutRetentionPolicy",
          "logs:TagLogGroup", "logs:UntagLogGroup", "logs:TagResource", "logs:UntagResource"
        ]
        Resource = ["arn:aws:logs:eu-west-2:1234567890:log-group:/aws/lambda/agent-platform-*"]
      },
      {
        Sid    = "CloudWatchAlarmsWrite"
        Effect = "Allow"
        Action = ["cloudwatch:PutMetricAlarm", "cloudwatch:TagResource", "cloudwatch:UntagResource"]
        Resource = ["arn:aws:cloudwatch:eu-west-2:1234567890:alarm:agent-platform-*"]
      },
      {
        Sid    = "EventBridgeWrite"
        Effect = "Allow"
        Action = [
          "events:PutRule", "events:TagResource", "events:UntagResource",
          "events:EnableRule", "events:DisableRule"
        ]
        Resource = ["arn:aws:events:eu-west-2:1234567890:rule/agent-platform-*"]
      },
      {
        Sid    = "IAMRoleCreateBounded"
        Effect = "Allow"
        Action = ["iam:CreateRole"]
        Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
      },
      {
        Sid    = "IAMRoleMetadataWrite"
        Effect = "Allow"
        Action = ["iam:TagRole", "iam:UntagRole", "iam:UpdateRole", "iam:UpdateRoleDescription"]
        Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
      },
      {
        Sid    = "IAMRolePolicyWrite"
        Effect = "Allow"
        Action = ["iam:PutRolePolicy", "iam:DeleteRolePolicy"]
        Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
      },
      {
        Sid    = "OIDCProviderReconcile"
        Effect = "Allow"
        Action = [
          "iam:UpdateOpenIDConnectProviderThumbprint", "iam:AddClientIDToOpenIDConnectProvider",
          "iam:TagOpenIDConnectProvider", "iam:UntagOpenIDConnectProvider"
        ]
        Resource = ["arn:aws:iam::1234567890:oidc-provider/token.actions.githubusercontent.com"]
      },
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
"""

# The boundary ceiling must grant every iam: action the identity half grants (or a covering pattern),
# or check_identity_iam_actions_subset_of_boundary / the companion ceiling assertion fire.
_APPLY_POLICY_TAIL = """    ]
  })
}

resource "aws_iam_policy" "github_ci_apply_boundary" {
  name = "test-apply-boundary"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DataPlaneAllow"
        Effect   = "Allow"
        Action   = [
          "lambda:*", "logs:*", "cloudwatch:*", "events:*",
          "iam:GetOpenIDConnectProvider", "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:AddClientIDToOpenIDConnectProvider", "iam:TagOpenIDConnectProvider",
          "iam:UntagOpenIDConnectProvider",
          "iam:CreateRole", "iam:TagRole", "iam:UntagRole", "iam:UpdateRole",
          "iam:UpdateRoleDescription", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:PassRole"
        ]
        Resource = ["*"]
      }
    ]
  })
}
"""


# The policy-architecture split: the same LambdaRead grant, relocated OUT of the inline identity
# policy into a customer-managed policy. Relocating a read grant must not read as deleting it, so
# the gate takes the UNION of the two -- but only when an attachment actually binds the managed
# policy to the apply role.
_READS_POLICY = """
resource "aws_iam_policy" "github_ci_apply_reads" {
  name = "test-apply-reads"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
      }
    ]
  })
}
"""

_READS_ATTACHMENT = """
resource "aws_iam_role_policy_attachment" "apply_reads" {
  role       = aws_iam_role.github_ci_apply.name
  policy_arn = aws_iam_policy.github_ci_apply_reads.arn
}
"""

_FOREIGN_ATTACHMENT = """
resource "aws_iam_role_policy_attachment" "elsewhere" {
  role       = aws_iam_role.some_other_role.name
  policy_arn = aws_iam_policy.github_ci_apply_reads.arn
}
"""


def _apply_policy(read_sids: str = _READ_SID_LAMBDA) -> str:
    """The synthetic bootstrap HCL: a caller-chosen READ half over the shared WRITE half."""
    return _APPLY_POLICY_HEAD + read_sids + _WRITE_SIDS + _APPLY_POLICY_TAIL


def _write_ci_refresh_read_fixture(
    tmp_path: Path,
    bootstrap_body: str | None = None,
    oidc_body: str | None = None,
    resources_body: str | None = None,
    include_bootstrap: bool = True,
    include_oidc: bool = True,
) -> None:
    """Minimal fully-covered fixture for validate_ci_refresh_read_coverage() (rec-2702).

    Mirrors the shape of tests/test_validate_ci_refresh_read_coverage.py's fixture builder --
    kept independent (not imported) so this module's test coverage stands on its own, matching
    the scripts/checks/** -> tests/test_validate.py convention (test_coverage_checker.py).
    """
    default_bootstrap = _apply_policy()
    default_oidc = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*", "lambda:List*"]
    resources = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
  }
}

resource "aws_iam_role_policy" "github_ci_planner" {
  name   = "test-planner"
  role   = "test-planner-role"
  policy = data.aws_iam_policy_document.github_ci_planner.json
}

data "aws_iam_policy_document" "github_ci_planner" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}
"""
    default_resources = """
resource "aws_lambda_function" "known_fn" {
  function_name = "agent-platform-known-fn"
}
"""
    if include_bootstrap:
        bootstrap_dir = tmp_path / "terraform" / "bootstrap"
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        (bootstrap_dir / "github_ci_apply.tf").write_text(
            bootstrap_body if bootstrap_body is not None else default_bootstrap, encoding="utf-8"
        )

    personal_dir = tmp_path / "terraform" / "personal"
    personal_dir.mkdir(parents=True, exist_ok=True)
    if include_oidc:
        (personal_dir / "oidc.tf").write_text(oidc_body if oidc_body is not None else default_oidc, encoding="utf-8")
    (personal_dir / "resources.tf").write_text(
        resources_body if resources_body is not None else default_resources, encoding="utf-8"
    )


# WHY THE SYNTHETIC TREES ARE EXEMPT FROM A RULE THE REAL TREE SATISFIES (read before "fixing" this):
#
# design (c) rule 2 (_write_symmetry.check_read_write_scope_parity) requires each write-managed type's
# READ grant to cover everything its WRITE grant can create. This package's fixtures deliberately pair
# PREFIX write grants (function:agent-platform-*, secret:agent-platform-*, rule/agent-platform-*) with
# LITERAL read ARNs (agent-platform-known-fn, agent-platform-known-secret-*, ...). That mismatch IS the
# test apparatus: it is the only reason gap_fn / gap_secret / orphan_role are detectable as read gaps.
# Widening the fixtures' reads to the write prefixes would make every gap resource covered and delete
# the read-gap cases this package exists to test; narrowing their writes below the discovered prefixes
# would fail design (a) discovery. The two obligations are jointly unsatisfiable for THIS fixture, so
# rule 2 is neutralised for the synthetic trees ONLY.
#
# Production is untouched: READ_SCOPE_PARITY_EXEMPT still carries exactly one real entry
# (aws_iam_role), the real tree is asserted against the unpatched rule by
# test_real_tree.py::test_real_tree_passes, and rule 2's own positive/negative cases live in
# tests/checks/iam_tf/test__write_symmetry.py. Never widen the production exemption table, the
# transitive-skip set, or the rule to make a synthetic fixture green.
_SYNTHETIC_PARITY_WHY = (
    "SYNTHETIC-FIXTURE EXEMPTION (tests only): this fixture pairs prefix WRITE grants with literal "
    "READ ARNs on purpose, because that is what makes its read-gap resources detectable -- see the "
    "comment above this constant in conftest.py. The real tree is asserted against the UNPATCHED rule."
)


@pytest.fixture
def synthetic_parity_exempt() -> Iterator[None]:
    """Neutralise design (c) rule 2 for a synthetic fixture tree, and only for it."""
    exemptions = {rtype: _SYNTHETIC_PARITY_WHY for rtype in WRITE_COVERAGE}
    with patch.dict("scripts.checks.iam_tf._write_symmetry.READ_SCOPE_PARITY_EXEMPT", exemptions, clear=False):
        yield
