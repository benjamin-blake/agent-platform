"""Tests for _read_coverage._read_root_text (PLAN-terraform-decompose-oidc-rename).

Split out of test__read_coverage.py (SLOC governance, Decision 128) -- a second test file for the
same source module rather than a package conversion, since scripts/test_coverage_checker.py's
_CONCERN_SPLIT_TEST_PACKAGES registry is unaffected either way (it only requires the mapped
test__read_coverage.py to exist, which it still does)."""

from __future__ import annotations

from pathlib import Path

from scripts.checks.iam_tf._read_coverage import _parse_bootstrap_statements, _read_root_text


class TestReadRootText:
    """_read_root_text is the terraform-decompose-oidc-rename repoint: every bootstrap policy
    re-read consumes a WHOLE root's concatenated *.tf text instead of one hardcoded filename, so a
    `policy = local.<name>` hoist resolves even when the local lives in a sibling file."""

    def test_concatenates_sibling_tf_files_in_sorted_order(self, tmp_path: Path) -> None:
        root = tmp_path / "terraform" / "bootstrap"
        root.mkdir(parents=True)
        (root / "b_second.tf").write_text("SECOND\n", encoding="utf-8")
        (root / "a_first.tf").write_text("FIRST\n", encoding="utf-8")
        text = _read_root_text(root)
        assert text.index("FIRST") < text.index("SECOND"), "must concatenate in sorted filename order"

    def test_empty_or_missing_root_returns_empty_string_not_raises(self, tmp_path: Path) -> None:
        assert _read_root_text(tmp_path / "does" / "not" / "exist") == ""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        assert _read_root_text(empty_dir) == ""

    def test_hoisted_local_resolves_when_the_local_lives_in_a_sibling_file(self, tmp_path: Path) -> None:
        """THE regression this repoint exists to fix: before the split, the hoisted local and its
        consuming resource were always in the SAME single file that every caller hardcoded. Reading
        just the resource's own file (the pre-repoint behaviour) cannot see a local relocated to a
        sibling -- only concatenating the whole root can."""
        root = tmp_path / "terraform" / "bootstrap"
        root.mkdir(parents=True)
        (root / "github_ci_apply_policy.tf").write_text(
            """
locals {
  github_ci_apply_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaRead"
        Effect = "Allow"
        Action = ["lambda:Get*"]
        Resource = ["arn:aws:lambda:eu-west-2:1234567890:function:agent-platform-known-fn"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "x"
  role   = "y"
  policy = local.github_ci_apply_policy_json
}
""",
            encoding="utf-8",
        )
        (root / "github_ci_apply.tf").write_text('resource "aws_iam_role" "github_ci_apply" {}\n', encoding="utf-8")

        # RED proof: reading only the resource's own file, the hoisted local is invisible.
        single_file_text = (root / "github_ci_apply.tf").read_text(encoding="utf-8")
        assert _parse_bootstrap_statements(single_file_text, "github_ci_apply") == []

        # GREEN: concatenating the whole root resolves the cross-file hoist.
        root_text = _read_root_text(root)
        stmts = _parse_bootstrap_statements(root_text, "github_ci_apply")
        assert len(stmts) == 1
        assert stmts[0]["sid"] == "LambdaRead"

    def test_decoy_sibling_file_with_a_same_shaped_local_does_not_satisfy_a_different_resource(self, tmp_path: Path) -> None:
        """Root-wide parsing must widen only the RESOLUTION pool, never the ATTRIBUTION scope: a
        decoy local of a similar shape in a sibling file must not be picked up by an unrelated
        resource that references a DIFFERENTLY-NAMED local."""
        root = tmp_path / "terraform" / "bootstrap"
        root.mkdir(parents=True)
        (root / "decoy.tf").write_text(
            """
locals {
  decoy_policy_json = jsonencode({
    Statement = [{ Sid = "DecoySid", Effect = "Allow", Action = ["s3:GetObject"], Resource = ["*"] }]
  })
}
""",
            encoding="utf-8",
        )
        (root / "github_ci_apply.tf").write_text(
            """
resource "aws_iam_role_policy" "github_ci_apply" {
  name   = "x"
  role   = "y"
  policy = local.github_ci_apply_policy_json
}
""",
            encoding="utf-8",
        )
        root_text = _read_root_text(root)
        # The referenced local (github_ci_apply_policy_json) is never defined anywhere -- the decoy
        # local carries a different name, so resolution must fail closed (empty), not borrow the decoy.
        assert _parse_bootstrap_statements(root_text, "github_ci_apply") == []
