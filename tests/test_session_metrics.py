#!/usr/bin/env python3
"""Unit tests for session timing and test_functions_added in scripts/session/metrics.py."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load the module under test
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "session" / "metrics.py"
_spec = importlib.util.spec_from_file_location("session_metrics", _MODULE_PATH)
assert _spec and _spec.loader
_metrics = importlib.util.module_from_spec(_spec)
sys.modules["session_metrics"] = _metrics
_spec.loader.exec_module(_metrics)  # type: ignore[union-attr]


class TestSessionTiming:
    def test_session_start_read_from_preflight(self, tmp_path: Path) -> None:
        report = tmp_path / ".preflight-report.json"
        report.write_text(json.dumps({"session_start": "2026-03-28T10:00:00+00:00"}), encoding="utf-8")
        with patch("session_metrics.PREFLIGHT_REPORT", report):
            result = _metrics.get_session_start()
        assert result == "2026-03-28T10:00:00+00:00"

    def test_session_start_returns_none_when_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / ".preflight-report.json"
        with patch("session_metrics.PREFLIGHT_REPORT", missing):
            result = _metrics.get_session_start()
        assert result is None

    def test_session_start_returns_none_on_invalid_json(self, tmp_path: Path) -> None:
        report = tmp_path / ".preflight-report.json"
        report.write_text("not valid json", encoding="utf-8")
        with patch("session_metrics.PREFLIGHT_REPORT", report):
            result = _metrics.get_session_start()
        assert result is None

    def test_session_duration_computed(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        log_file = tmp_path / ".session-metrics-log.jsonl"
        report = tmp_path / ".preflight-report.json"
        report.write_text(json.dumps({"session_start": "2026-03-28T10:00:00+00:00"}), encoding="utf-8")

        with (
            patch("session_metrics.get_git_stats", return_value=(0, 0, 0)),
            patch("session_metrics.count_test_functions_added", return_value=0),
            patch("session_metrics.get_pytest_results", return_value=(5, 0)),
            patch("session_metrics.get_coverage", return_value="75%"),
            patch("session_metrics.get_current_branch", return_value="agent/test"),
            patch("session_metrics.PREFLIGHT_REPORT", report),
            patch("session_metrics.METRICS_LOG", log_file),
            patch("session_metrics.datetime") as mock_dt,
            patch("sys.argv", ["session_metrics.py"]),
        ):
            # Mock datetime.now to return a fixed time 30 minutes after session_start
            from datetime import datetime, timezone

            mock_dt.now.return_value = datetime(2026, 3, 28, 10, 30, 0, tzinfo=timezone.utc)
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.isoformat = datetime.isoformat
            with pytest.raises(SystemExit):
                _metrics.main()

        assert log_file.exists()
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert entry["session_start"] == "2026-03-28T10:00:00+00:00"
        assert entry["session_duration_minutes"] == 30.0

    def test_session_duration_none_when_no_preflight(self, tmp_path: Path) -> None:
        log_file = tmp_path / ".session-metrics-log.jsonl"
        missing_report = tmp_path / ".missing.json"

        with (
            patch("session_metrics.get_git_stats", return_value=(0, 0, 0)),
            patch("session_metrics.count_test_functions_added", return_value=0),
            patch("session_metrics.get_pytest_results", return_value=(5, 0)),
            patch("session_metrics.get_coverage", return_value="N/A"),
            patch("session_metrics.get_current_branch", return_value="main"),
            patch("session_metrics.PREFLIGHT_REPORT", missing_report),
            patch("session_metrics.METRICS_LOG", log_file),
            patch("sys.argv", ["session_metrics.py"]),
        ):
            with pytest.raises(SystemExit):
                _metrics.main()

        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert entry["session_start"] is None
        assert entry["session_duration_minutes"] is None


class TestTestFunctionsAdded:
    def test_counts_difference_vs_main(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            cmd_str = " ".join(str(c) for c in cmd)
            if "grep" in cmd_str and "-c" in cmd_str:
                r.stdout = "tests/test_foo.py:3\ntests/test_bar.py:2\n"  # 5 total on branch
            elif "origin/main:tests/test_foo.py" in cmd_str:
                r.stdout = "def test_a():\ndef test_b():\n"  # 2 on main
            elif "origin/main:tests/test_bar.py" in cmd_str:
                r.stdout = "def test_c():\n"  # 1 on main
            elif "origin/main:tests/" in cmd_str:
                r.stdout = "test_foo.py\ntest_bar.py\n"  # directory listing
            else:
                r.stdout = ""
            return r

        with patch("session_metrics.subprocess.run", side_effect=mock_run):
            # branch: 5 total, main: 3 total (test_a, test_b, test_c)
            result = _metrics.count_test_functions_added()
        assert result == 2  # 5 branch - 3 main

    def test_returns_zero_when_no_new_tests(self) -> None:
        def mock_run(cmd: list, **kwargs: object) -> MagicMock:
            r = MagicMock()
            r.returncode = 0
            cmd_str = " ".join(str(c) for c in cmd)
            if "grep" in cmd_str:
                r.stdout = "tests/test_foo.py:2\n"
            elif "show origin/main:tests/" in cmd_str and ".py" not in cmd_str:
                r.stdout = "test_foo.py\n"
            elif "show origin/main:tests/test_foo.py" in cmd_str:
                r.stdout = "def test_a():\ndef test_b():\n"
            else:
                r.stdout = ""
            r.stderr = ""
            return r

        with patch("session_metrics.subprocess.run", side_effect=mock_run):
            result = _metrics.count_test_functions_added()
        assert result == 0


class TestStepCounterArgs:
    """Tests for --steps-total and --steps-friction CLI arguments."""

    def _run_main_with_steps(
        self,
        tmp_path: Path,
        steps_total: int,
        steps_friction: int,
    ) -> dict:
        """Helper: run main() with step args and return the JSONL entry."""
        log_file = tmp_path / ".session-metrics-log.jsonl"
        missing_report = tmp_path / ".missing.json"
        argv = [
            "session_metrics.py",
            "--steps-total",
            str(steps_total),
            "--steps-friction",
            str(steps_friction),
        ]
        with (
            patch("session_metrics.get_git_stats", return_value=(0, 0, 0)),
            patch("session_metrics.count_test_functions_added", return_value=0),
            patch("session_metrics.get_pytest_results", return_value=(0, 0)),
            patch("session_metrics.get_coverage", return_value="N/A"),
            patch("session_metrics.get_current_branch", return_value="agent/test"),
            patch("session_metrics.PREFLIGHT_REPORT", missing_report),
            patch("session_metrics.METRICS_LOG", log_file),
            patch("sys.argv", argv),
        ):
            with pytest.raises(SystemExit):
                _metrics.main()
        return json.loads(log_file.read_text(encoding="utf-8").strip())

    def test_steps_total_and_friction_recorded(self, tmp_path: Path) -> None:
        """steps_total and steps_friction are written to the JSONL record."""
        entry = self._run_main_with_steps(tmp_path, steps_total=10, steps_friction=2)
        assert entry["steps_total"] == 10
        assert entry["steps_friction"] == 2

    def test_friction_rate_computed(self, tmp_path: Path) -> None:
        """friction_rate = steps_friction / steps_total when steps_total > 0."""
        entry = self._run_main_with_steps(tmp_path, steps_total=10, steps_friction=2)
        assert entry["friction_rate"] == pytest.approx(0.2)

    def test_friction_rate_zero_when_steps_total_is_zero(self, tmp_path: Path) -> None:
        """friction_rate defaults to 0.0 when steps_total == 0 (avoid divide-by-zero)."""
        entry = self._run_main_with_steps(tmp_path, steps_total=0, steps_friction=0)
        assert entry["friction_rate"] == 0.0

    def test_defaults_are_zero(self, tmp_path: Path) -> None:
        """When no step-counter args are passed, steps_total and steps_friction default to 0."""
        log_file = tmp_path / ".session-metrics-log.jsonl"
        missing_report = tmp_path / ".missing.json"
        with (
            patch("session_metrics.get_git_stats", return_value=(0, 0, 0)),
            patch("session_metrics.count_test_functions_added", return_value=0),
            patch("session_metrics.get_pytest_results", return_value=(0, 0)),
            patch("session_metrics.get_coverage", return_value="N/A"),
            patch("session_metrics.get_current_branch", return_value="agent/test"),
            patch("session_metrics.PREFLIGHT_REPORT", missing_report),
            patch("session_metrics.METRICS_LOG", log_file),
            patch("sys.argv", ["session_metrics.py"]),
        ):
            with pytest.raises(SystemExit):
                _metrics.main()
        entry = json.loads(log_file.read_text(encoding="utf-8").strip())
        assert entry["steps_total"] == 0
        assert entry["steps_friction"] == 0
        assert entry["friction_rate"] == 0.0
