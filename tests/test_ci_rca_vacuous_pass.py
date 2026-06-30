"""Tests for scripts/ci_rca_vacuous_pass.py (100% coverage)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ci_rca_vacuous_pass import (  # noqa: E402
    _TEST_FILE_RE,
    _UNDETERMINED,
    compute_coverage_regression,
    compute_merge_gate_test_coverage,
    deleted_test_files,
    merged_diff_files,
    parse_vacuous_pass,
)


class TestParseVacuousPass:
    def test_collected_zero_no_deselection_returns_true(self):
        log = "collected 0 items\n========================= no tests ran in 0.01s ========================="
        assert parse_vacuous_pass(log) is True

    def test_collected_zero_with_deselection_returns_false(self):
        log = "collected 1 item / 1 deselected / 0 selected\n========================= no tests ran ="
        assert parse_vacuous_pass(log) is False

    def test_multiple_items_collected_returns_false(self):
        log = "collected 5 items\n5 passed in 0.12s"
        assert parse_vacuous_pass(log) is False

    def test_no_pytest_summary_returns_undetermined(self):
        log = "Unexpected error occurred\nProcess exited with code 1"
        assert parse_vacuous_pass(log) == _UNDETERMINED

    def test_no_tests_ran_without_deselected_returns_true(self):
        log = "no tests ran in 0.00s"
        assert parse_vacuous_pass(log) is True

    def test_no_tests_ran_with_deselected_returns_false(self):
        log = "collected 2 items / 2 deselected\nno tests ran"
        assert parse_vacuous_pass(log) is False

    def test_empty_log_returns_undetermined(self):
        assert parse_vacuous_pass("") == _UNDETERMINED

    def test_case_insensitive(self):
        log = "Collected 0 Items"
        assert parse_vacuous_pass(log) is True

    def test_large_deselected_count_returns_false(self):
        log = "collected 10 items / 10 deselected / 0 selected"
        assert parse_vacuous_pass(log) is False

    def test_never_silently_false_on_ambiguous(self):
        """Non-parseable log must return undetermined, never False (Decision 55 fail-loud)."""
        result = parse_vacuous_pass("some unrelated output\nrandom lines")
        assert result == _UNDETERMINED

    def test_fixture_vacuous_collected0(self):
        log = (ROOT / "tests" / "fixtures" / "ci_rca" / "vacuous_collected0.log").read_text()
        assert parse_vacuous_pass(log) is True

    def test_fixture_all_integration_deselected(self):
        log = (ROOT / "tests" / "fixtures" / "ci_rca" / "all_integration_deselected.log").read_text()
        assert parse_vacuous_pass(log) is False

    def test_fixture_unparseable(self):
        log = (ROOT / "tests" / "fixtures" / "ci_rca" / "unparseable.log").read_text()
        assert parse_vacuous_pass(log) == _UNDETERMINED


class TestMergedDiffFiles:
    def test_returns_list_on_success(self, tmp_path):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "scripts/foo.py\ntests/test_foo.py\n"
            result = merged_diff_files()
        assert isinstance(result, list)
        assert "scripts/foo.py" in result
        assert "tests/test_foo.py" in result

    def test_returns_undetermined_on_nonzero_exit(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "fatal: ambiguous argument 'HEAD^'"
            result = merged_diff_files()
        assert result == _UNDETERMINED

    def test_returns_undetermined_on_exception(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = merged_diff_files()
        assert result == _UNDETERMINED

    def test_empty_diff_returns_empty_list(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            result = merged_diff_files()
        assert result == []


class TestDeletedTestFiles:
    def test_returns_only_test_files(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "tests/test_foo.py\nscripts/bar.py\n"
            result = deleted_test_files()
        assert isinstance(result, list)
        assert "tests/test_foo.py" in result
        assert "scripts/bar.py" not in result

    def test_returns_undetermined_on_failure(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "fatal: ambiguous argument 'HEAD^'"
            result = deleted_test_files()
        assert result == _UNDETERMINED

    def test_empty_when_no_deleted_tests(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "scripts/bar.py\n"
            result = deleted_test_files()
        assert result == []

    def test_uses_diff_filter_D(self):
        with patch("scripts.ci_rca_vacuous_pass.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            deleted_test_files()
        cmd = mock_run.call_args[0][0]
        assert "--diff-filter=D" in cmd


class TestComputeMergeGateTestCoverage:
    def test_source_only_diff_returns_not_selected(self):
        merged = ["scripts/foo.py", "scripts/bar.py"]
        result = compute_merge_gate_test_coverage("validate_sloc_limits", merged)
        assert result == "not_selected"

    def test_changed_test_file_returns_selected(self):
        merged = ["scripts/foo.py", "tests/test_foo.py"]
        result = compute_merge_gate_test_coverage("validate_sloc_limits", merged)
        assert result == "selected"

    def test_undetermined_input_returns_undetermined(self):
        result = compute_merge_gate_test_coverage("validate_sloc_limits", _UNDETERMINED)
        assert result == _UNDETERMINED

    def test_empty_diff_returns_not_selected(self):
        result = compute_merge_gate_test_coverage("validate_sloc_limits", [])
        assert result == "not_selected"

    def test_test_file_regex_matches_correctly(self):
        assert _TEST_FILE_RE.match("tests/test_foo.py")
        assert _TEST_FILE_RE.match("tests/subdir/test_bar.py")
        assert not _TEST_FILE_RE.match("scripts/test_foo.py")
        assert not _TEST_FILE_RE.match("tests/conftest.py")
        assert not _TEST_FILE_RE.match("tests/test_foo/helper.py")

    def test_integration_test_file_still_selected(self):
        # Path selection is orthogonal to -m "not integration"; selection is by path only
        merged = ["tests/test_integration_foo.py"]
        result = compute_merge_gate_test_coverage("any_check", merged)
        assert result == "selected"


class TestComputeCoverageRegression:
    def test_deleted_test_returns_true(self):
        deleted = ["tests/test_foo.py"]
        assert compute_coverage_regression(deleted) is True

    def test_no_deleted_tests_returns_false(self):
        assert compute_coverage_regression([]) is False

    def test_undetermined_returns_undetermined(self):
        assert compute_coverage_regression(_UNDETERMINED) == _UNDETERMINED

    def test_multiple_deleted_tests_returns_true(self):
        deleted = ["tests/test_a.py", "tests/test_b.py"]
        assert compute_coverage_regression(deleted) is True
