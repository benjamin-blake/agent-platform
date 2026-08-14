"""End-to-end tests for validate_ci_refresh_read_coverage() (rec-2702 anti-recurrence,
PLAN-ci-apply-grant-coupling). Concern-split module (rec-2709 Wave 1) -- see test_real_tree.py for
the other module of this package. The synthetic-fixture builder (_apply_policy /
_write_ci_refresh_read_fixture) moved into conftest.py (PLAN-terraform-decompose-oidc-rename, SLOC
governance) so it can be shared with this package's other concern-split modules without a
cross-test import.

FIXTURE CONTRACT (PLAN-iam-write-surface-completion): the synthetic apply policy must satisfy every
obligation the gate now orchestrates -- design (a) discovery, design (b) lifecycle companions
(including the boundary DataPlaneAllow ceiling for every iam: companion) and design (c) rule 1 tag
symmetry -- not read coverage alone. The two large bootstrap bodies are therefore composed from ONE
shared write half (`_WRITE_SIDS` + `_apply_policy`, both in conftest.py) rather than hand-copied:
keeping two copies in sync with those tables is exactly the drift this package exists to catch.
Design (c) rule 2 (read scope >= write scope) is the one rule the fixture cannot satisfy -- it
pairs prefix WRITE grants with literal READ ARNs on purpose, which is what makes its read-gap
resources detectable -- so rule 2 is neutralised per-test by the `synthetic_parity_exempt` fixture
in this package's conftest.py (read its comment before changing anything). The REAL tree is
asserted against the unpatched rule in test_real_tree.py::test_real_tree_passes.
"""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_ci_refresh_read_coverage import validate_ci_refresh_read_coverage
from tests.checks.iam_tf.validate_ci_refresh_read_coverage.conftest import (
    _FOREIGN_ATTACHMENT,
    _READ_SID_OIDC,
    _READS_ATTACHMENT,
    _READS_POLICY,
    _apply_policy,
    _write_ci_refresh_read_fixture,
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
        assert "terraform/bootstrap" in failed[0]

    def test_missing_oidc_file_fails_loud(self, tmp_path: Path) -> None:
        """oidc.tf specifically absent, but the personal root still has OTHER .tf content
        (resources.tf, always written by the fixture) -- root-wide parsing means this is no longer
        a "cannot read the root at all" case, it is "the root doesn't define the planner role"."""
        _write_ci_refresh_read_fixture(tmp_path, include_oidc=False)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "could not resolve github_ci_planner role policy" in failed[0]
        assert "terraform/personal" in failed[0]

    def test_empty_personal_root_fails_loud(self, tmp_path: Path) -> None:
        """The genuine "cannot read" branch now requires the WHOLE root to be empty, not just
        oidc.tf -- a real regression this branch guards is a personal root with zero *.tf files."""
        bootstrap_dir = tmp_path / "terraform" / "bootstrap"
        bootstrap_dir.mkdir(parents=True, exist_ok=True)
        (bootstrap_dir / "github_ci_apply.tf").write_text(_apply_policy(), encoding="utf-8")
        (tmp_path / "terraform" / "personal").mkdir(parents=True, exist_ok=True)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert len(failed) == 1
        assert "cannot read" in failed[0]
        assert "terraform/personal" in failed[0]

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

    def test_read_and_write_coverage_resolve_across_split_roots(self, tmp_path: Path, synthetic_parity_exempt: None) -> None:
        """terraform-decompose-oidc-rename: prove coverage parity still resolves when EACH root is
        split across sibling files -- the identity policy separated from the boundary policy in
        terraform/bootstrap/, and the planner role+document separated from the shared refresh-read
        document in terraform/personal/."""
        _write_ci_refresh_read_fixture(tmp_path)

        bootstrap_dir = tmp_path / "terraform" / "bootstrap"
        full_bootstrap = (bootstrap_dir / "github_ci_apply.tf").read_text(encoding="utf-8")
        boundary_marker = 'resource "aws_iam_policy" "github_ci_apply_boundary"'
        split_idx = full_bootstrap.index(boundary_marker)
        (bootstrap_dir / "github_ci_apply.tf").write_text(
            "# retained -- role/trust only in the real split\n", encoding="utf-8"
        )
        (bootstrap_dir / "github_ci_apply_policy.tf").write_text(full_bootstrap[:split_idx], encoding="utf-8")
        (bootstrap_dir / "github_ci_apply_boundary.tf").write_text(full_bootstrap[split_idx:], encoding="utf-8")

        personal_dir = tmp_path / "terraform" / "personal"
        full_oidc = (personal_dir / "oidc.tf").read_text(encoding="utf-8")
        planner_marker = 'resource "aws_iam_role_policy" "github_ci_planner"'
        split_idx2 = full_oidc.index(planner_marker)
        (personal_dir / "oidc.tf").write_text(full_oidc[:split_idx2], encoding="utf-8")
        (personal_dir / "oidc_pipeline_roles.tf").write_text(full_oidc[split_idx2:], encoding="utf-8")

        # RED proof: reading only the retained files (the pre-repoint single-file behaviour), the
        # planner role and both policy documents are gone.
        assert "github_ci_planner" not in (personal_dir / "oidc.tf").read_text(encoding="utf-8")
        assert "Statement" not in (bootstrap_dir / "github_ci_apply.tf").read_text(encoding="utf-8")

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_ci_refresh_read_coverage(failed)
        assert failed == [], failed

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
