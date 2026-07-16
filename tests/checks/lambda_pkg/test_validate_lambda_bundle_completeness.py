"""Tests for validate_lambda_bundle_completeness()."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks.lambda_pkg.validate_lambda_bundle_completeness import validate_lambda_bundle_completeness


class TestValidateLambdaBundleCompleteness:
    """Tests for validate_lambda_bundle_completeness() -- bundle check wrapper."""

    def test_passes_when_cmd_check_bundles_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_bundles.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert failed == []

    def test_fails_when_cmd_check_bundles_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_bundles.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert "Lambda bundle completeness" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert "Lambda bundle completeness" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_check_bundles.side_effect = RuntimeError("staging failed")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_bundle_completeness(failed)
        assert "Lambda bundle completeness" in failed
