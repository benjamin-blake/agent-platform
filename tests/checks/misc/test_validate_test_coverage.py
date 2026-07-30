"""Tests for validate_test_coverage()."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks.misc.validate_test_coverage import validate_test_coverage


class TestValidateTestCoverage:
    """Tests for validate_test_coverage()."""

    @pytest.fixture(autouse=True)
    def _clear_subprocess_guard(self, monkeypatch):
        """Remove the conftest recursion guard so coverage logic is exercised."""
        monkeypatch.delenv("_COVERAGE_SUBPROCESS", raising=False)

    def test_passes_when_no_changed_files(self) -> None:
        """No failures when get_changed_source_files returns empty list."""
        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = []

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []

    def test_passes_when_all_test_files_exist(self, tmp_path: Path) -> None:
        """No failures when all changed files have corresponding test files."""
        source = tmp_path / "src" / "config.py"
        source.parent.mkdir(parents=True)
        source.write_text("def foo(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (True, "test file found")
        mock_checker.check_per_file_coverage.return_value = []

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []

    def test_fails_when_test_file_missing(self, tmp_path: Path) -> None:
        """Appends to failed list when a changed file has no test file."""
        source = tmp_path / "src" / "new_module.py"
        source.parent.mkdir(parents=True)
        source.write_text("def bar(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (False, "missing test file: tests/test_new_module.py")

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert len(failed) == 1
        assert "Test coverage check" in failed[0]

    def test_skips_when_checker_not_found(self) -> None:
        """No failures (and no exception) when test_coverage_checker.py is absent."""
        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=None):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []

    def test_passes_when_baseline_entry_present_and_measured_meets_it(self, tmp_path: Path) -> None:
        """Baseline-aware gate branch: an entry present means the threshold is < 100.

        check_per_file_coverage() is fully delegated to (mocked) here -- its own baseline
        compare logic is covered directly in tests/checks/misc/test_coverage_baseline.py -- so
        this only proves validate_test_coverage() treats a non-empty return as a failure and an
        empty return (the baseline-satisfied case) as a pass, exactly as it does for the
        unbaselined 100% case above."""
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("def foo(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (True, "test file found")
        mock_checker.check_per_file_coverage.return_value = []  # baselined at 75.4, measured 75.5

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert failed == []

    def test_fails_when_measured_below_baseline_entry(self, tmp_path: Path) -> None:
        """A changed file WITH a baseline entry still fails when measured < that threshold."""
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("def foo(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (True, "test file found")
        mock_checker.check_per_file_coverage.return_value = ["scripts/ops_writer.py: 70.0% line coverage (expected >= 75.4%)"]

        with patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker):
            failed: list[str] = []
            validate_test_coverage(failed)

        assert len(failed) == 1
        assert "Coverage below 100%" in failed[0]
