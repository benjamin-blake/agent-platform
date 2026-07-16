"""Tests for validate_terraform_try()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_terraform_try import validate_terraform_try


class TestValidateTerraformTry:
    """Tests for validate_terraform_try()."""

    validate_terraform_try = staticmethod(validate_terraform_try)

    def test_passes_when_filemd5_inside_try(self, tmp_path: Path) -> None:
        """No failure when filemd5() is wrapped in try()."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "main.tf").write_text(
            'source_code_hash = try(\n  filemd5("build/lambda.zip"),\n  md5("fallback")\n)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert failed == []

    def test_fails_when_filemd5_not_inside_try(self, tmp_path: Path) -> None:
        """Fails when filemd5() is used without wrapping try()."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "bad.tf").write_text(
            'source_code_hash = filemd5("build/lambda.zip")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed

    def test_passes_with_no_tf_files(self, tmp_path: Path) -> None:
        """No failure when terraform directory has no .tf files."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert failed == []

    def test_fails_when_bare_file_not_inside_try(self, tmp_path: Path) -> None:
        """Fails when file() is used directly without wrapping try()."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "bad.tf").write_text(
            'policy = file("policy.json")\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed

    def test_passes_when_file_inside_nested_try(self, tmp_path: Path) -> None:
        """No failure when file() is nested inside a try() as a fallback arg."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "ok.tf").write_text(
            'hash = try(\n  filemd5("build/lambda.zip"),\n  md5(file("ok.tf"))\n)\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert failed == []

    def test_retry_identifier_not_treated_as_try(self, tmp_path: Path) -> None:
        """Functions named retry() are NOT treated as try() (word boundary check)."""
        tf_dir = tmp_path / "terraform"
        tf_dir.mkdir()
        (tf_dir / "retry.tf").write_text(
            'hash = retry(filemd5("build/lambda.zip"))\n',
            encoding="utf-8",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            self.validate_terraform_try(failed)
        assert "Terraform try() lint" in failed
