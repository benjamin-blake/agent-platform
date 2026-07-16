"""Tests for validate_iam_runner_policy()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_iam_runner_policy import validate_iam_runner_policy


class TestValidateIamRunnerPolicy:
    """Tests for validate_iam_runner_policy()."""

    def test_passes_when_all_actions_present(self, tmp_path: Path) -> None:
        """No failures when all manifest actions are in the Terraform file."""
        manifest = tmp_path / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("actions: [{action: 's3:GetObject'}]\n", encoding="utf-8")

        terraform = tmp_path / "terraform" / "ec2_runner.tf"
        terraform.parent.mkdir()
        terraform.write_text('Action = ["s3:GetObject"]\n', encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert failed == []

    def test_fails_when_action_missing(self, tmp_path: Path) -> None:
        """Fails when an action in the manifest is not in the Terraform file."""
        manifest = tmp_path / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("actions: [{action: 's3:DeleteObject'}]\n", encoding="utf-8")

        terraform = tmp_path / "terraform" / "ec2_runner.tf"
        terraform.parent.mkdir()
        terraform.write_text('Action = ["s3:GetObject"]\n', encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert len(failed) == 1
        assert "Missing actions" in failed[0]
        assert "s3:DeleteObject" in failed[0]

    def test_requires_quoted_match(self, tmp_path: Path) -> None:
        """Actions must appear within quotes to prevent partial matches."""
        manifest = tmp_path / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("actions: [{action: 's3:Get'}]\n", encoding="utf-8")

        terraform = tmp_path / "terraform" / "ec2_runner.tf"
        terraform.parent.mkdir()
        # s3:Get matches part of s3:GetObject, but we want exact quoted match
        terraform.write_text('Action = ["s3:GetObject"]\n', encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        assert len(failed) == 1
        assert "s3:Get" in failed[0]

    def test_skips_when_manifest_missing(self, tmp_path: Path, capsys) -> None:
        """Gracefully skips if config/agent/validate/iam_runner_manifest.yaml does not exist."""
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_iam_runner_policy(failed)

        captured = capsys.readouterr()
        assert "SKIPPED: IAM runner manifest missing" in captured.out
        assert failed == []
