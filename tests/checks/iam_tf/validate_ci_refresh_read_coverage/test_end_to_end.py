"""End-to-end tests for validate_ci_refresh_read_coverage() (rec-2702 anti-recurrence,
PLAN-ci-apply-grant-coupling). Concern-split module (rec-2709 Wave 1) -- see
test_helpers.py and test_real_tree.py for the other two modules of this package."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_ci_refresh_read_coverage import validate_ci_refresh_read_coverage


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
    default_bootstrap = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*", "lambda:List*"]
        Resource = [
          "arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"
        ]
      },
      {
        Sid    = "LambdaFunctionWrite"
        Effect = "Allow"
        Action = ["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"]
      },
      {
        Sid    = "CloudWatchLogsWrite"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:PutRetentionPolicy"]
        Resource = ["arn:aws:logs:eu-west-2:1234567890:log-group:/aws/lambda/agent-platform-*"]
      },
      {
        Sid    = "CloudWatchAlarmsWrite"
        Effect = "Allow"
        Action = ["cloudwatch:PutMetricAlarm"]
        Resource = ["arn:aws:cloudwatch:eu-west-2:1234567890:alarm:agent-platform-*"]
      },
      {
        Sid    = "EventBridgeWrite"
        Effect = "Allow"
        Action = ["events:PutRule"]
        Resource = ["arn:aws:events:eu-west-2:1234567890:rule/agent-platform-*"]
      },
      {
        Sid    = "IAMRoleCreateBounded"
        Effect = "Allow"
        Action = ["iam:CreateRole"]
        Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
      }
    ]
  })
}
"""
    default_oidc = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*", "lambda:List*"]
    resources = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
  }
}

resource "aws_iam_role_policy" "github_ci_plan" {
  name   = "test-plan"
  role   = "test-plan-role"
  policy = data.aws_iam_policy_document.github_ci_plan.json
}

data "aws_iam_policy_document" "github_ci_plan" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}

resource "aws_iam_role_policy" "github_ci_drift" {
  name   = "test-drift"
  role   = "test-drift-role"
  policy = data.aws_iam_policy_document.github_ci_drift.json
}

data "aws_iam_policy_document" "github_ci_drift" {
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


class TestValidateCiRefreshReadCoverageEndToEnd:
    """End-to-end validate_ci_refresh_read_coverage() tests covering the top-level fail-loud
    branches (missing files, unparseable HCL, empty resource set, unresolvable names) that the
    plan-scoped fixture in tests/test_validate_ci_refresh_read_coverage.py does not exercise."""

    def test_missing_bootstrap_file_fails_loud(self, tmp_path: Path) -> None:
        _write_ci_refresh_read_fixture(tmp_path, include_bootstrap=False)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "cannot read" in failed[0]
        assert "github_ci_apply.tf" in failed[0]

    def test_missing_oidc_file_fails_loud(self, tmp_path: Path) -> None:
        _write_ci_refresh_read_fixture(tmp_path, include_oidc=False)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "cannot read" in failed[0]
        assert "oidc.tf" in failed[0]

    def test_bootstrap_without_apply_policy_fails_loud(self, tmp_path: Path) -> None:
        _write_ci_refresh_read_fixture(tmp_path, bootstrap_body="# no aws_iam_role_policy block here\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "no statements parsed from the github_ci_apply policy" in failed[0]

    def test_oidc_missing_drift_role_fails_loud(self, tmp_path: Path) -> None:
        broken_oidc = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_ci_plan" {
  name   = "test-plan"
  role   = "test-plan-role"
  policy = data.aws_iam_policy_document.github_ci_plan.json
}

data "aws_iam_policy_document" "github_ci_plan" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}
"""
        _write_ci_refresh_read_fixture(tmp_path, oidc_body=broken_oidc)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "could not resolve github_ci_plan/github_ci_drift role policies" in failed[0]

    def test_no_resources_discovered_fails_loud(self, tmp_path: Path) -> None:
        _write_ci_refresh_read_fixture(tmp_path)
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.iam_tf.validate_ci_refresh_read_coverage._scan_resources",
                return_value=([], {}, {}),
            ),
        ):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "no terraform resources discovered" in failed[0]

    def test_unresolvable_name_treated_as_uncovered(self, tmp_path: Path) -> None:
        resources_body = """
resource "aws_lambda_function" "mystery_fn" {
  function_name = local.undefined_local
}
"""
        _write_ci_refresh_read_fixture(tmp_path, resources_body=resources_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "could not resolve a name/id" in failed[0]
        assert "mystery_fn" in failed[0]

    def test_fully_covered_synthetic_tree_passes(self, tmp_path: Path) -> None:
        """The default (no-gap) fixture passes cleanly -- reaches the terminal PASS print."""
        _write_ci_refresh_read_fixture(tmp_path)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert failed == []

    def test_unmapped_resource_type_fails_loud(self, tmp_path: Path) -> None:
        resources_body = """
resource "aws_kms_key" "unclassified" {
  description = "not in any coverage-map category"
}
"""
        _write_ci_refresh_read_fixture(tmp_path, resources_body=resources_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "unmapped resource type" in failed[0]
        assert "aws_kms_key" in failed[0]

    def test_iam_role_enumerated_and_uncovered_names_the_role(self, tmp_path: Path) -> None:
        """An aws_iam_role not literally enumerated in any role policy's iam:GetRole grant fails,
        naming the role and the (apply/plan/drift) policy it is missing from."""
        resources_body = """
resource "aws_iam_role" "orphan_role" {
  name = "agent-platform-orphan-role"
}
"""
        _write_ci_refresh_read_fixture(tmp_path, resources_body=resources_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 3  # apply, plan, drift
        for f in failed:
            assert "aws_iam_role" in f
            assert "orphan_role" in f
            assert "is not refresh-read-covered" in f

    def test_iam_role_substring_collision_fails_loud_end_to_end(self, tmp_path: Path) -> None:
        """H-finding regression guard (code-review 2026-07-15): an aws_iam_role whose name is a
        literal substring-PREFIX of a longer enumerated ARN -- but is NOT itself enumerated -- must
        FAIL loud. Before the boundary-anchoring fix it silently PASSED, defeating the enumerated-IAM
        invariant this verifier exists to guarantee (Decision 35/98/55)."""
        # The three role policies enumerate `agent-platform-known-fn-role` (a longer name).
        iam_grant = "arn:aws:iam::1234567890:role/agent-platform-known-fn-role"  # pragma: allowlist secret
        bootstrap_body = f"""
resource "aws_iam_role_policy" "github_ci_apply" {{
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [
      {{
        Sid    = "IAMRolesRead"
        Effect = "Allow"
        Action = ["iam:GetRole"]
        Resource = ["{iam_grant}"]
      }}
    ]
  }})
}}
"""
        oidc_body = f"""
data "aws_iam_policy_document" "ci_full_refresh_read" {{
  statement {{
    sid       = "IAMCIRolesRead"
    effect    = "Allow"
    actions   = ["iam:GetRole"]
    resources = ["{iam_grant}"]
  }}
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
        # The resource role `agent-platform-known-fn` is a substring prefix of the enumerated
        # `agent-platform-known-fn-role`, but is NOT itself enumerated -- must fail in all 3 roles.
        resources_body = """
resource "aws_iam_role" "collide_role" {
  name = "agent-platform-known-fn"
}
"""
        _write_ci_refresh_read_fixture(
            tmp_path, bootstrap_body=bootstrap_body, oidc_body=oidc_body, resources_body=resources_body
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        collide_findings = [f for f in failed if "collide_role" in f]
        assert len(collide_findings) == 3, failed  # apply, plan, drift -- not silently covered

    def test_oidc_provider_url_resolves_to_host(self, tmp_path: Path) -> None:
        """aws_iam_openid_connect_provider's `url` attribute is resolved and the scheme stripped
        before matching against the enumerated oidc-provider ARN."""
        bootstrap_body = """
resource "aws_iam_role_policy" "github_ci_apply" {
  name = "test-apply"
  role = "test-apply-role"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "OIDCProviderRead"
        Effect = "Allow"
        Action = ["iam:GetOpenIDConnectProvider"]
        Resource = ["arn:aws:iam::1234567890:oidc-provider/token.actions.githubusercontent.com"]
      },
      {
        Sid    = "LambdaFunctionWrite"
        Effect = "Allow"
        Action = ["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-*"]
      },
      {
        Sid    = "CloudWatchLogsWrite"
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:PutRetentionPolicy"]
        Resource = ["arn:aws:logs:eu-west-2:1234567890:log-group:/aws/lambda/agent-platform-*"]
      },
      {
        Sid    = "CloudWatchAlarmsWrite"
        Effect = "Allow"
        Action = ["cloudwatch:PutMetricAlarm"]
        Resource = ["arn:aws:cloudwatch:eu-west-2:1234567890:alarm:agent-platform-*"]
      },
      {
        Sid    = "EventBridgeWrite"
        Effect = "Allow"
        Action = ["events:PutRule"]
        Resource = ["arn:aws:events:eu-west-2:1234567890:rule/agent-platform-*"]
      },
      {
        Sid    = "IAMRoleCreateBounded"
        Effect = "Allow"
        Action = ["iam:CreateRole"]
        Resource = ["arn:aws:iam::1234567890:role/agent-platform-*"]
      }
    ]
  })
}
"""
        oidc_body = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "OIDCProviderRead"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = ["arn:aws:iam::1234567890:oidc-provider/token.actions.githubusercontent.com"]
  }
}

resource "aws_iam_role_policy" "github_ci_plan" {
  name   = "test-plan"
  role   = "test-plan-role"
  policy = data.aws_iam_policy_document.github_ci_plan.json
}

data "aws_iam_policy_document" "github_ci_plan" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}

resource "aws_iam_role_policy" "github_ci_drift" {
  name   = "test-drift"
  role   = "test-drift-role"
  policy = data.aws_iam_policy_document.github_ci_drift.json
}

data "aws_iam_policy_document" "github_ci_drift" {
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}
"""
        resources_body = """
resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
}
"""
        _write_ci_refresh_read_fixture(
            tmp_path, bootstrap_body=bootstrap_body, oidc_body=oidc_body, resources_body=resources_body
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert failed == []
