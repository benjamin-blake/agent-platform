"""Tests for validate_lambda_deploy_gating()."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks.lambda_pkg.validate_lambda_deploy_gating import validate_lambda_deploy_gating


class TestValidateLambdaDeployGating:
    """Tests for validate_lambda_deploy_gating() -- advisory deploy scope check."""

    def test_no_changed_files_skips_silently(self) -> None:
        mock_lm = MagicMock()
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert failed == []
        mock_lm.compute_affected_artifacts.assert_not_called()

    def test_reports_affected_artifact_without_failing(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.return_value = {"data-pipeline": ["src/data/handlers/fetch_handler.py"]}
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["src/data/handlers/fetch_handler.py"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert failed == []
        mock_lm.compute_affected_artifacts.assert_called_once_with(["src/data/handlers/fetch_handler.py"])

    def test_no_affected_artifacts_is_advisory_pass(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.return_value = {}
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["docs/README.md"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert failed == []

    def test_fails_on_import_error(self) -> None:
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": None}),
            patch("scripts.checks._common.get_changed_files", return_value=["src/some/file.py"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert "Lambda deploy gating" in failed

    def test_fails_on_unexpected_exception(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.side_effect = RuntimeError("load failed")
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["src/some/file.py"]),
        ):
            failed: list[str] = []
            validate_lambda_deploy_gating(failed)
        assert "Lambda deploy gating" in failed
