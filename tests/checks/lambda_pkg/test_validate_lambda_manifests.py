"""Tests for validate_lambda_manifests()."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks.lambda_pkg.validate_lambda_manifests import validate_lambda_manifests


class TestValidateLambdaManifests:
    """Tests for validate_lambda_manifests() -- schema validation wrapper."""

    def test_passes_when_cmd_validate_returns_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 0
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert failed == []

    def test_fails_when_cmd_validate_returns_nonzero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.return_value = 1
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed

    def test_fails_on_import_error(self) -> None:
        with patch.dict(sys.modules, {"scripts.lambda_manifest": None}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.cmd_validate.side_effect = RuntimeError("unexpected boom")
        with patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}):
            failed: list[str] = []
            validate_lambda_manifests(failed)
        assert "Lambda manifest schema validation" in failed
