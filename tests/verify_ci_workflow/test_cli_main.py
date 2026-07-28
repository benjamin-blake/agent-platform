"""Tests for scripts/verify_ci_workflow.py's main() CLI dispatcher (pre-existing gap surfaced
by PLAN-ci-rca-ops-plane-coverage's touch on this file -- see _COMMANDS dispatch, usage error,
AssertionError-to-FAIL translation, and the `if __name__` entrypoint)."""

from __future__ import annotations

import runpy
import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.verify_ci_workflow import main


class TestMainDispatch:
    def test_no_args_runs_all_checks(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["verify_ci_workflow.py"])
        checks = {"one": MagicMock(), "two": MagicMock()}
        with patch.dict("scripts.verify_ci_workflow._COMMANDS", checks, clear=True):
            main()
        assert all(check.call_count == 1 for check in checks.values())
        assert capsys.readouterr().out.strip() == "OK"

    def test_unknown_command_prints_usage_and_exits_1(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["verify_ci_workflow.py", "not-a-real-command"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
        assert "Usage:" in capsys.readouterr().err

    def test_assertion_error_prints_fail_and_exits_1(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        # _COMMANDS binds each command name directly to its check function object at module load
        # time, so patching the module-level `_check_canary` name would not affect the already-
        # captured dict entry -- patch the dict entry itself instead.
        monkeypatch.setattr(sys, "argv", ["verify_ci_workflow.py", "canary"])
        with patch.dict(
            "scripts.verify_ci_workflow._COMMANDS",
            {"canary": MagicMock(side_effect=AssertionError("boom"))},
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
        assert "FAIL: boom" in capsys.readouterr().err

    def test_passing_command_prints_ok(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["verify_ci_workflow.py", "ci-rca-filter"])
        main()
        assert capsys.readouterr().out.strip() == "OK"


class TestCliMain:
    # This module is already imported at collection time by other test files in this package, so
    # it is already in sys.modules by the time runpy re-executes it below -- the standard, benign
    # runpy caveat for this pattern (docs.python.org/3/library/runpy.html).
    @pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
    def test_runpy_main_entrypoint_runs_and_prints_ok(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        monkeypatch.setattr(sys, "argv", ["verify_ci_workflow.py", "ci-rca-filter"])
        runpy.run_module("scripts.verify_ci_workflow", run_name="__main__")
        assert capsys.readouterr().out.strip() == "OK"
