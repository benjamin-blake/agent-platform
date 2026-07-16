"""Tests for validate_invoke_implies_resolve() (T2.34:c2, Decision 104)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_invoke_implies_resolve import validate_invoke_implies_resolve


def _write_oidc_tf(tmp_path: Path, body: str) -> None:
    oidc_path = tmp_path / "terraform" / "personal" / "oidc.tf"
    oidc_path.parent.mkdir(parents=True, exist_ok=True)
    oidc_path.write_text(body, encoding="utf-8")


class TestValidateInvokeImpliesResolve:
    """Tests for validate_invoke_implies_resolve() (T2.34:c2, Decision 104)."""

    def test_invoke_implies_resolve_passes_on_real_composed_oidc_tf(self) -> None:
        """The real terraform/personal/oidc.tf: all invoking roles (branch, pr, plan, drift)
        resolve SSM via source_policy_documents composition -- zero failures."""
        failed: list[str] = []
        validate_invoke_implies_resolve(failed)
        assert failed == []

    def test_invoke_implies_resolve_vacuous_pass_for_non_invoking_role(self, tmp_path: Path) -> None:
        """A role whose composed statements never invoke the DuckLake reader/writer passes
        without needing SSM at all."""
        _write_oidc_tf(
            tmp_path,
            """
            data "aws_iam_policy_document" "github_ci_noop" {
              statement {
                sid       = "S3List"
                effect    = "Allow"
                actions   = ["s3:ListBucket"]
                resources = ["*"]
              }
            }

            resource "aws_iam_role_policy" "github_ci_noop" {
              name   = "agent-platform-github-ci-noop"
              role   = aws_iam_role.github_ci_noop.id
              policy = data.aws_iam_policy_document.github_ci_noop.json
            }
            """,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert failed == []

    def test_invoke_implies_resolve_fails_when_composition_omits_ssm(self, tmp_path: Path) -> None:
        """A role that invokes the ducklake writer but never composes an SSM-granting
        document is a genuine T2.34:c2 violation (rec-2363-class drift)."""
        _write_oidc_tf(
            tmp_path,
            """
            data "aws_iam_policy_document" "github_ci_violator" {
              statement {
                sid    = "DuckLakeInvokeCI"
                effect = "Allow"
                actions = ["lambda:InvokeFunction", "lambda:InvokeFunctionUrl"]
                resources = [
                  aws_lambda_function.ducklake_writer.arn,
                  "${aws_lambda_function.ducklake_writer.arn}:*",
                ]
              }
            }

            resource "aws_iam_role_policy" "github_ci_violator" {
              name   = "agent-platform-github-ci-violator"
              role   = aws_iam_role.github_ci_violator.id
              policy = data.aws_iam_policy_document.github_ci_violator.json
            }
            """,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert len(failed) == 1
        assert "github_ci_violator" in failed[0]
        assert "lacks ssm:Get*" in failed[0]

    def test_invoke_implies_resolve_passes_via_transitive_source_composition(self, tmp_path: Path) -> None:
        """A role composing a document that itself sources the SSM fragment (two levels of
        source_policy_documents) still resolves -- composition is followed transitively."""
        _write_oidc_tf(
            tmp_path,
            """
            data "aws_iam_policy_document" "ci_ssm_refresh_read" {
              statement {
                sid       = "SSMParameterRead"
                effect    = "Allow"
                actions   = ["ssm:Get*", "ssm:Describe*", "ssm:List*"]
                resources = ["arn:aws:ssm:eu-west-2:1234567890:parameter/agent-platform/*"]
              }
            }

            data "aws_iam_policy_document" "ci_full_refresh_read" {
              source_policy_documents = [data.aws_iam_policy_document.ci_ssm_refresh_read.json]

              statement {
                sid       = "TfstateRead"
                effect    = "Allow"
                actions   = ["s3:GetObject"]
                resources = ["arn:aws:s3:::agent-platform-data-lake/tfstate/personal/*"]
              }
            }

            data "aws_iam_policy_document" "github_ci_composer" {
              source_policy_documents = [data.aws_iam_policy_document.ci_full_refresh_read.json]

              statement {
                sid    = "DuckLakeWriterInvoke"
                effect = "Allow"
                actions = ["lambda:InvokeFunction"]
                resources = [
                  aws_lambda_function.ducklake_writer.arn,
                ]
              }
            }

            resource "aws_iam_role_policy" "github_ci_composer" {
              name   = "agent-platform-github-ci-composer"
              role   = aws_iam_role.github_ci_composer.id
              policy = data.aws_iam_policy_document.github_ci_composer.json
            }
            """,
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert failed == []

    def test_invoke_implies_resolve_fails_loud_when_no_policy_documents_found(self, tmp_path: Path) -> None:
        """An oidc.tf that no longer matches the expected HCL shape fails loud rather than
        silently passing vacuously (Decision 55)."""
        _write_oidc_tf(tmp_path, "# empty -- no aws_iam_policy_document or aws_iam_role_policy blocks\n")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_invoke_implies_resolve(failed)
        assert len(failed) == 1
        assert "no aws_iam_policy_document / aws_iam_role_policy blocks found" in failed[0]
