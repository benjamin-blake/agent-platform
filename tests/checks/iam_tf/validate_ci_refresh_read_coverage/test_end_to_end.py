"""End-to-end tests for validate_ci_refresh_read_coverage() (rec-2702 anti-recurrence,
PLAN-ci-apply-grant-coupling). Concern-split module (rec-2709 Wave 1) -- see
test_helpers.py and test_real_tree.py for the other two modules of this package.

FIXTURE CONTRACT (PLAN-iam-write-surface-completion): the synthetic apply policy must satisfy every
obligation the gate now orchestrates -- design (a) discovery, design (b) lifecycle companions
(including the boundary DataPlaneAllow ceiling for every iam: companion) and design (c) rule 1 tag
symmetry -- not read coverage alone. The two large bootstrap bodies are therefore composed from ONE
shared write half (`_WRITE_SIDS` + `_apply_policy`) rather than hand-copied: keeping two copies in
sync with those tables is exactly the drift this package exists to catch. Design (c) rule 2 (read
scope >= write scope) is the one rule the fixture cannot satisfy -- it pairs prefix WRITE grants with
literal READ ARNs on purpose, which is what makes its read-gap resources detectable -- so rule 2 is
neutralised per-test by the `synthetic_parity_exempt` fixture in this package's conftest.py (read its
comment before changing anything). The REAL tree is asserted against the unpatched rule in
test_real_tree.py::test_real_tree_passes.
"""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_ci_refresh_read_coverage import validate_ci_refresh_read_coverage

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

    def test_oidc_missing_planner_role_fails_loud(self, tmp_path: Path) -> None:
        """T2.49 / DEP-12: github_ci_plan + github_ci_drift merged into the single
        github_ci_planner role -- when its role-policy block is entirely absent from oidc.tf,
        resolution fails loud."""
        broken_oidc = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "LambdaRead"
    effect    = "Allow"
    actions   = ["lambda:Get*"]
    resources = ["*"]
  }
}
"""
        _write_ci_refresh_read_fixture(tmp_path, oidc_body=broken_oidc)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "could not resolve github_ci_planner role policy" in failed[0]

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

    def test_unresolvable_name_treated_as_uncovered(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        resources_body = """
resource "aws_lambda_function" "mystery_fn" {
  function_name = local.undefined_local
}
"""
        _write_ci_refresh_read_fixture(tmp_path, resources_body=resources_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        # Scoped to the READ half: this fixture's personal tree also exercises the design (a)
        # write-discovery sweep, whose findings are a different assertion's business.
        unresolved = [f for f in failed if "could not resolve a name/id" in f]
        assert len(unresolved) == 1, failed
        assert "mystery_fn" in unresolved[0]

    def test_fully_covered_synthetic_tree_passes(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """The default (no-gap) fixture passes cleanly -- reaches the terminal PASS print.

        "No gap" now spans read coverage, design (a) discovery, design (b) lifecycle companions and
        design (c) rule 1 -- see the module docstring for the one rule this fixture is exempt from."""
        _write_ci_refresh_read_fixture(tmp_path)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert failed == []

    def test_relocated_reads_policy_counts_when_attached(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """The LambdaRead grant lives ONLY in the attached managed policy -- the inline identity
        policy has no read half at all. Relocating a grant must not read as deleting it: the gate
        scores the apply role on the UNION, so the tree still passes."""
        bootstrap_body = _apply_policy(read_sids="") + _READS_POLICY + _READS_ATTACHMENT
        _write_ci_refresh_read_fixture(tmp_path, bootstrap_body=bootstrap_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert failed == []

    def test_unattached_reads_policy_fails_loud(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """A declared-but-unattached managed policy is INERT: its grants never reach the role, yet
        every static grep still finds them in the file. That silent gap must fail loud."""
        _write_ci_refresh_read_fixture(tmp_path, bootstrap_body=_apply_policy() + _READS_POLICY)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1, failed
        assert "no aws_iam_role_policy_attachment" in failed[0]
        assert "would be inert" in failed[0]

    def test_attachment_binding_another_role_does_not_count_as_attached(
        self, tmp_path: Path, synthetic_parity_exempt: None
    ) -> None:
        """Both halves of the attachment are asserted. An `aws_iam_role_policy_attachment` that
        carries the reads policy but binds it to some OTHER role leaves the apply role without it --
        matching the resource type alone would pass this and ship the same inert grants."""
        bootstrap_body = _apply_policy() + _READS_POLICY + _FOREIGN_ATTACHMENT
        _write_ci_refresh_read_fixture(tmp_path, bootstrap_body=bootstrap_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1, failed
        assert "would be inert" in failed[0]

    def test_unmapped_resource_type_fails_loud(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """An unclassified type fails loud on BOTH halves -- read coverage cannot classify it, and
        design (a) discovery finds it neither WRITE_COVERAGE-mapped nor WRITE_EXEMPT_TYPES-exempt."""
        resources_body = """
resource "aws_kms_key" "unclassified" {
  description = "not in any coverage-map category"
}
"""
        _write_ci_refresh_read_fixture(tmp_path, resources_body=resources_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        unmapped_read = [f for f in failed if "unmapped resource type" in f]
        assert len(unmapped_read) == 1, failed
        assert "aws_kms_key" in unmapped_read[0]
        unmapped_write = [f for f in failed if "neither WRITE_COVERAGE-mapped nor WRITE_EXEMPT_TYPES-exempt" in f]
        assert len(unmapped_write) == 1, failed
        assert "aws_kms_key" in unmapped_write[0]

    def test_iam_role_enumerated_and_uncovered_names_the_role(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """An aws_iam_role not literally enumerated in any role policy's iam:GetRole grant fails,
        naming the role and the (apply/planner) policy it is missing from."""
        resources_body = """
resource "aws_iam_role" "orphan_role" {
  name = "agent-platform-orphan-role"
}
"""
        _write_ci_refresh_read_fixture(tmp_path, resources_body=resources_body)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        # apply, planner (T2.49 / DEP-12: plan+drift merged, 3 -> 2), scoped to the READ half.
        uncovered = [f for f in failed if "is not refresh-read-covered" in f]
        assert len(uncovered) == 2, failed
        for f in uncovered:
            assert "aws_iam_role" in f
            assert "orphan_role" in f

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

resource "aws_iam_role_policy" "github_ci_planner" {{
  name   = "test-planner"
  role   = "test-planner-role"
  policy = data.aws_iam_policy_document.github_ci_planner.json
}}

data "aws_iam_policy_document" "github_ci_planner" {{
  source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]
}}
"""
        # The resource role `agent-platform-known-fn` is a substring prefix of the enumerated
        # `agent-platform-known-fn-role`, but is NOT itself enumerated -- must fail in both roles
        # (T2.49 / DEP-12: plan+drift merged into the single planner role, 3 -> 2).
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
        assert len(collide_findings) == 2, failed  # apply, planner -- not silently covered

    def test_oidc_provider_url_resolves_to_host(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """aws_iam_openid_connect_provider's `url` attribute is resolved and the scheme stripped
        before matching against the enumerated oidc-provider ARN.

        Composed from the shared WRITE half with the OIDC read Sid swapped in, so the provider's
        design (a) write grant and its design (b) update-phase companions (thumbprint reconcile,
        AddClientID, tag/untag) come from one place rather than a hand-copied second policy."""
        bootstrap_body = _apply_policy(_READ_SID_OIDC)
        oidc_body = """
data "aws_iam_policy_document" "ci_full_refresh_read" {
  statement {
    sid       = "OIDCProviderRead"
    effect    = "Allow"
    actions   = ["iam:GetOpenIDConnectProvider"]
    resources = ["arn:aws:iam::1234567890:oidc-provider/token.actions.githubusercontent.com"]
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
