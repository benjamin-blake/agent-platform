"""Tests for validate_ci_rca_trigger() -- the presubmit wrapper around _check_ci_rca_filter."""

import sys
from unittest.mock import MagicMock, patch

from scripts.checks.ci_guards.validate_ci_rca_trigger import validate_ci_rca_trigger


class TestValidateCiRcaTrigger:
    """Tests for validate_ci_rca_trigger() -- the presubmit wrapper around _check_ci_rca_filter."""

    def test_passes_when_guard_succeeds(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter = MagicMock()

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert failed == []
        mock_module._check_ci_rca_filter.assert_called_once()

    def test_appends_to_failed_when_guard_raises(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("main-branch gate missing")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert len(failed) == 1
        assert "ci-rca trigger gate" in failed[0]

    def test_no_error_propagation_on_assertion(self) -> None:
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = AssertionError("something wrong")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert failed == ["ci-rca trigger gate"]

    def test_no_error_propagation_on_runtime_error(self) -> None:
        """rec-2027: validate_ci_rca_trigger catches non-AssertionError and records failure."""
        mock_module = MagicMock()
        mock_module._check_ci_rca_filter.side_effect = RuntimeError("unexpected boom")

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_rca_trigger(failed)

        assert len(failed) == 1
        assert "ci-rca trigger gate" in failed[0]
