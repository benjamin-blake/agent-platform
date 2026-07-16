"""run_coverage_check() / ensure_fresh_dq_results() / whole-repo SLOC scan coverage tests --
orchestrator residue (rec-2709 Wave 1)."""

import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.fixtures.subprocess_stubs import _mock_completed
from tests.fixtures.validate_module import _validate

validate_sloc_limits = _validate.validate_sloc_limits
validate_cc_limits = _validate.validate_cc_limits
ensure_fresh_dq_results = _validate.ensure_fresh_dq_results
run_coverage_check = _validate.run_coverage_check
get_changed_files = _validate.get_changed_files
ROOT = _validate.ROOT
_update_sloc_budgets = _validate._update_sloc_budgets
iter_gated_py_files = _validate.iter_gated_py_files


class TestRunCoverageCheck:
    """Tests for run_coverage_check() — the --coverage advisory mode."""

    def test_run_coverage_check_no_changed_files_prints_message(self, capsys) -> None:
        """When there are no changed files, the function reports nothing to check."""
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "coverage" in captured.out.lower()
        assert "No changed files" in captured.out

    def test_run_coverage_check_all_covered(self, capsys) -> None:
        """When every changed file is covered, the report says 'All scope files covered'."""
        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/ops_data_portal.py"]),
            patch("scripts.verifiers.check_coverage", return_value=[]),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "All scope files covered" in captured.out

    def test_run_coverage_check_lists_uncovered(self, capsys) -> None:
        """Uncovered files are printed line-by-line under the report header."""
        with (
            patch(
                "scripts.checks._common.get_changed_files",
                return_value=["docs/foo.md", "scripts/ops_data_portal.py"],
            ),
            patch(
                "scripts.verifiers.check_coverage",
                return_value=["docs/foo.md"],
            ),
        ):
            run_coverage_check()
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        assert "- docs/foo.md" in captured.out
        assert "Advisory only" in captured.out

    def test_run_coverage_check_uses_supplied_changed_files(self, capsys) -> None:
        """A supplied changed_files list is used verbatim, skipping the get_changed_files() call
        (VF-02(d): the --pre closure reuses its already-computed diff -- budget-safe)."""
        with (
            patch("scripts.checks._common.get_changed_files") as mock_get_changed,
            patch("scripts.verifiers.check_coverage", return_value=["docs/foo.md"]),
        ):
            run_coverage_check(changed_files=["docs/foo.md", "scripts/ops_data_portal.py"])
        captured = capsys.readouterr()
        assert "1 of 2 scope files lack verifier coverage" in captured.out
        mock_get_changed.assert_not_called()


class TestEnsureFreshDqResults:
    """Tests for ensure_fresh_dq_results() — the DQ runner auto-invoke."""

    @pytest.fixture(autouse=True)
    def _inject_boto3_stub(self):
        """Ensure boto3 is in sys.modules so patch("boto3.Session") resolves on CI runners where boto3 is not installed."""
        if "boto3" not in sys.modules:
            sys.modules["boto3"] = MagicMock()
            yield
            del sys.modules["boto3"]
        else:
            yield

    def test_ensure_fresh_dq_runs_when_cache_missing(self, tmp_path: Path, capsys) -> None:
        """No dq-latest.json on disk: credential check runs, then data_quality_runner is invoked."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache missing" in captured.out
        assert "data_quality_runner" in captured.out
        # One subprocess call: data_quality_runner only (credential check is boto3).
        assert mock_run.call_count == 1
        runner_cmd = mock_run.call_args_list[0].args[0]
        assert "data_quality_runner" in " ".join(runner_cmd)
        assert failed == []

    def test_ensure_fresh_dq_runs_when_cache_stale(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json older than the freshness window: re-runs the runner."""

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Backdate mtime by 2 hours -- well past the 1h freshness window.
        old_mtime = time.time() - 2 * 3600
        os.utime(str(dq_file), (old_mtime, old_mtime))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.return_value = {"Account": "123"}
            mock_run.return_value = _mock_completed(0)
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache stale" in captured.out
        assert "data_quality_runner" in captured.out
        assert mock_run.call_count == 1
        assert failed == []

    def test_ensure_fresh_dq_skips_when_cache_fresh(self, tmp_path: Path, capsys) -> None:
        """dq-latest.json modified within the last hour: skip with a clear message."""
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        dq_file = dq_dir / "dq-latest.json"
        dq_file.write_text("{}", encoding="utf-8")
        # Default mtime is 'now', well inside the 1h freshness window.

        with patch("scripts.checks._common.ROOT", tmp_path), patch("scripts.checks._common.run") as mock_run:
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "DQ cache fresh" in captured.out
        # Fresh cache must short-circuit before invoking subprocess at all.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_sso_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57: failed boto3 credential check prints actionable guidance and skips."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.return_value.client.return_value.get_caller_identity.side_effect = Exception("Token has expired")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        # No subprocess calls -- the runner was never invoked after the credential failure.
        assert mock_run.call_count == 0
        assert failed == []

    def test_ensure_fresh_dq_skips_when_credentials_unavailable(self, tmp_path: Path, capsys) -> None:
        """Decision 57: any boto3 credential error must skip with guidance, not crash."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("boto3.Session") as mock_session,
            patch("scripts.checks._common.run") as mock_run,
        ):
            mock_session.side_effect = Exception("ProfileNotFound")
            failed: list[str] = []
            ensure_fresh_dq_results(failed)

        captured = capsys.readouterr()
        assert "credentials not available" in captured.out and "skipping" in captured.out
        assert mock_run.call_count == 0
        assert failed == []


class TestWholeRepoScanCoverage:
    """Tests for the Decision 130 whole-repo scan extension (tests/ is now gated)."""

    def _write_budget(self, tmp_path: Path, entries: dict[str, int]) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["budgets:"]
        for k, v in entries.items():
            lines.append(f"  {k}: {v}")
        (config_dir / "sloc_budgets.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_oversized_unregistered_tests_file_fails(self, tmp_path: Path) -> None:
        """A tests/ file over 500 SLOC with no budget entry fails validate_sloc_limits."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big_thing.py").write_text("x = 1\n" * 501, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert len(failed) == 1
        assert "SLOC limits" in failed[0]

    def test_registered_tests_file_at_budget_passes(self, tmp_path: Path) -> None:
        """A tests/ file registered at/under its budget passes validate_sloc_limits."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big_thing.py").write_text("x = 1\n" * 600, encoding="utf-8")
        self._write_budget(tmp_path, {"tests/test_big_thing.py": 600})

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)

        assert failed == []

    def test_excluded_dir_is_not_gated(self, tmp_path: Path) -> None:
        """A file under an excluded dir (e.g. .venv/) is never scanned, regardless of SLOC."""
        venv_dir = tmp_path / ".venv" / "foo"
        venv_dir.mkdir(parents=True)
        (venv_dir / "vendored.py").write_text("x = 1\n" * 999, encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_sloc_limits(failed)
            gated = list(iter_gated_py_files())

        assert failed == []
        assert gated == []

    def test_all_three_gate_functions_share_one_scan(self, tmp_path: Path) -> None:
        """validate_sloc_limits, _update_sloc_budgets, and validate_cc_limits all consume the
        same iter_gated_py_files() -- one mock patched into both consumer modules is seen
        identically by all three, so the scan roots can never silently drift apart."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        only_file = tests_dir / "test_only.py"
        only_file.write_text("x = 1\n" * 501, encoding="utf-8")
        self._write_budget(tmp_path, {})

        shared_mock = MagicMock(side_effect=lambda: iter([only_file]))

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.sloc.sloc_limits.iter_gated_py_files", shared_mock),
            patch("scripts.checks.sloc.cc_limits.iter_gated_py_files", shared_mock),
        ):
            failed: list[str] = []
            validate_sloc_limits(failed)
            _update_sloc_budgets()
            validate_cc_limits(failed)

        assert shared_mock.call_count == 3  # validate_sloc_limits + _update_sloc_budgets + validate_cc_limits
        assert len(failed) == 1  # only the unregistered oversized file, from validate_sloc_limits

    def test_cc_limits_flags_branchy_function_in_tests_dir(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """validate_cc_limits now covers tests/: a >20-branch function there is flagged."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        branches = "\n".join(f"    if x == {i}: pass" for i in range(21))
        (tests_dir / "test_branchy.py").write_text(f"def test_heavy_dispatch(x):\n{branches}\n", encoding="utf-8")

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_cc_limits(failed)

        assert len(failed) == 1
        assert "Cyclomatic complexity" in failed[0]
        captured = capsys.readouterr()
        assert "test_heavy_dispatch" in captured.out
