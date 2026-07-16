"""Tests for validate_lambda_manifest_coverage()."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks.lambda_pkg.validate_lambda_manifest_coverage import validate_lambda_manifest_coverage


class TestValidateLambdaManifestCoverage:
    """Tests for validate_lambda_manifest_coverage() -- coverage gate wrapper."""

    def test_passes_when_cmd_check_coverage_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert failed == []

    def test_fails_when_cmd_check_coverage_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_coverage.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifest_coverage(failed)
        assert "Lambda manifest coverage" in failed
