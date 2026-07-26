"""Tests for validate_ci_workflow_guards() -- the presubmit wrapper around nine ci guards."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import _common
from scripts.checks.ci_guards.validate_ci_workflow_guards import validate_ci_workflow_guards

_MODULE_NAME = "scripts.checks.ci_guards.validate_ci_workflow_guards"


class TestValidateCiWorkflowGuards:
    """Tests for validate_ci_workflow_guards() -- the presubmit wrapper around nine ci guards."""

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

    def test_appends_ci_rca_fetch_classification_failure(self) -> None:
        """Proves the ninth guard is actually wired into the aggregator: the all-succeed case
        (test_passes_when_all_guards_succeed) patches a bare MagicMock() module which
        auto-creates every attribute, so it would pass even if ci-rca-fetch-classification were
        never added -- this negative-label case is the one that actually proves membership."""
        mock_module = MagicMock()
        mock_module._check_ci_rca_fetch_classification = MagicMock(side_effect=AssertionError("log-body grep reintroduced"))

        with patch.dict(sys.modules, {"scripts.verify_ci_workflow": mock_module}):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert len(failed) == 1
        assert "ci-workflow guard: ci-rca-fetch-classification" in failed[0]

    def test_removes_injected_sys_path_entry_on_the_way_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """rec-2027 defensive dance: when _ensure_root_on_path reports it injected ROOT (e.g. this
        module invoked in a context where the repo root was not already importable), the function
        removes that entry again on the way out rather than leaking it. Runs the real guards (not
        mocked) since only the sys.path bookkeeping is under test here. Builds a de-duplicated,
        single-occurrence sys.path via monkeypatch (rather than asserting against the ambient
        sys.path, which can carry duplicate entries under parallel/xdist test runs) so the
        removal assertion is deterministic."""
        root_str = str(_common.ROOT)
        controlled_path = [p for p in sys.path if p != root_str]
        controlled_path.append(root_str)
        monkeypatch.setattr(sys, "path", controlled_path)

        with patch("scripts.checks.ci_guards.validate_ci_workflow_guards._ensure_root_on_path", return_value=True):
            failed: list[str] = []
            validate_ci_workflow_guards(failed)

        assert root_str not in sys.path
        assert failed == []

    def test_module_level_guards_degrades_to_empty_on_import_failure(self) -> None:
        """AGENTS.md Safety ('Never raise exceptions during module import'): scripts/validate.py
        imports this aggregator module unconditionally, so a broken scripts.verify_ci_workflow
        must not raise while (re-)importing this module -- module-level _GUARDS degrades to an
        empty list instead, and validate_ci_workflow_guards() still reports the failure via its
        own call-time try/except (rec-2027) rather than the import itself crashing the run."""
        original_module = sys.modules.pop(_MODULE_NAME)
        try:
            with patch.dict(sys.modules, {"scripts.verify_ci_workflow": None}):
                reimported = importlib.import_module(_MODULE_NAME)
                assert reimported._GUARDS == []

                failed: list[str] = []
                reimported.validate_ci_workflow_guards(failed)
                assert len(failed) == 1
                assert "ci-workflow guards gate" in failed[0]
        finally:
            sys.modules[_MODULE_NAME] = original_module
