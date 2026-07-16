"""Tests for validate_ci_workflow_guards() -- the presubmit wrapper around four ci guards."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks.ci_guards.validate_ci_workflow_guards import validate_ci_workflow_guards


class TestValidateCiWorkflowGuards:
    """Tests for validate_ci_workflow_guards() -- the presubmit wrapper around four ci guards."""

    def test_passes_when_all_guards_succeed(self) -> None:
        mock_module = MagicMock()
        for attr in ("_check_jobs_and_flags", "_check_fetch_depth", "_check_concurrency", "_check_canary"):
            setattr(mock_module, attr, MagicMock())

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert failed == []

    def test_appends_failure_when_guard_raises_assertion(self) -> None:
        mock_module = MagicMock()
        mock_module._check_jobs_and_flags = MagicMock()
        mock_module._check_fetch_depth = MagicMock()
        mock_module._check_concurrency = MagicMock(side_effect=AssertionError("ci-runner still present"))
        mock_module._check_canary = MagicMock()

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "concurrency" in failed[0]

    def test_records_failure_on_runtime_error_no_propagation(self) -> None:
        """rec-2027: a non-AssertionError exception records a failure and does not propagate."""
        mock_module = MagicMock()
        mock_module._check_jobs_and_flags = MagicMock(side_effect=RuntimeError("disk full"))
        mock_module._check_fetch_depth = MagicMock()
        mock_module._check_concurrency = MagicMock()
        mock_module._check_canary = MagicMock()

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "jobs-and-flags" in failed[0]

    def test_records_failure_on_import_error_no_propagation(self) -> None:
        """rec-2027: an ImportError at guard-import time records a gate failure, no propagation."""
        # Setting the module to None in sys.modules makes `import` raise ImportError.
        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": None}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "ci-workflow guards gate" in failed[0]
