"""Tests for validate_lambda_deploy_gating()."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks import registry
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


class TestDeclaredAccounting:
    """Decision 170: BOTH early returns are empty DOMAINS -> examined(0)/vacuous, per constraint
    5b -- neither is a skip."""

    def test_no_changed_files_declares_examined_zero(self) -> None:
        mock_lm = MagicMock()
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch.object(registry, "examined") as mock_examined,
            patch.object(registry, "skipped") as mock_skipped,
        ):
            validate_lambda_deploy_gating([])
        mock_examined.assert_called_once_with(0, unit="changed_files")
        mock_skipped.assert_not_called()

    def test_no_affected_artifacts_declares_examined_zero(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.return_value = {}
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["docs/README.md"]),
            patch.object(registry, "examined") as mock_examined,
            patch.object(registry, "skipped") as mock_skipped,
        ):
            validate_lambda_deploy_gating([])
        mock_examined.assert_called_once_with(0, unit="affected_artifacts")
        mock_skipped.assert_not_called()

    def test_affected_artifacts_declares_examined_count(self) -> None:
        mock_lm = MagicMock()
        mock_lm.compute_affected_artifacts.return_value = {"data-pipeline": ["a.py"], "other": ["b.py"]}
        with (
            patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
            patch("scripts.checks._common.get_changed_files", return_value=["a.py", "b.py"]),
            patch.object(registry, "examined") as mock_examined,
        ):
            validate_lambda_deploy_gating([])
        mock_examined.assert_called_once_with(2, unit="affected_artifacts")


class TestSysPathInjection:
    """Coverage-debt payoff (Decision 170): both the injection and the not-already-present-so-
    inject-and-remove branches around the repo-root sys.path shim."""

    def test_injects_and_removes_repo_root_when_absent(self) -> None:
        """A full test-suite run can leave MULTIPLE duplicate root_str entries on sys.path
        (accumulated by unrelated modules) -- a single .remove() call does not guarantee
        absence, so this strips EVERY occurrence and restores the same count afterward."""
        from scripts.checks._common import ROOT

        root_str = str(ROOT)
        removed_count = 0
        while root_str in sys.path:
            sys.path.remove(root_str)
            removed_count += 1
        try:
            mock_lm = MagicMock()
            mock_lm.compute_affected_artifacts.return_value = {}
            with (
                patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
                patch("scripts.checks._common.get_changed_files", return_value=["a.py"]),
            ):
                failed: list[str] = []
                validate_lambda_deploy_gating(failed)
            assert failed == []
            assert root_str not in sys.path  # removed again on the way out
        finally:
            for _ in range(removed_count):
                sys.path.insert(0, root_str)

    def test_leaves_repo_root_alone_when_already_present(self) -> None:
        from scripts.checks._common import ROOT

        root_str = str(ROOT)
        already_present = root_str in sys.path
        if not already_present:
            sys.path.insert(0, root_str)
        try:
            mock_lm = MagicMock()
            mock_lm.compute_affected_artifacts.return_value = {}
            with (
                patch.dict(sys.modules, {"scripts.lambda_manifest": mock_lm}),
                patch("scripts.checks._common.get_changed_files", return_value=["a.py"]),
            ):
                failed: list[str] = []
                validate_lambda_deploy_gating(failed)
            assert failed == []
            assert root_str in sys.path  # left in place, never removed
        finally:
            if not already_present and root_str in sys.path:
                sys.path.remove(root_str)
