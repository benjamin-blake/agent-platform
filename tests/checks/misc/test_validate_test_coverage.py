"""Tests for validate_test_coverage()."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import registry
from scripts.checks._common import ROOT
from scripts.checks.misc.validate_test_coverage import _load_coverage_checker, validate_test_coverage


class TestLoadCoverageChecker:
    """Coverage-debt payoff (Decision 170): scripts/test_coverage_checker.py exists in this repo,
    so both the absent-checker branch and BOTH sys.path-injection branches are exercised for real."""

    def test_returns_none_when_checker_absent(self, tmp_path: Path) -> None:
        with patch("scripts.checks.misc.validate_test_coverage._common.ROOT", tmp_path):
            assert _load_coverage_checker() is None

    def test_loads_the_real_module_injecting_repo_root_onto_sys_path(self) -> None:
        """A full test-suite run can leave MULTIPLE duplicate root_str entries on sys.path
        (accumulated by unrelated modules) -- a single .remove() call does not guarantee
        absence, so this strips EVERY occurrence and restores the same count afterward."""
        root_str = str(ROOT)
        removed_count = 0
        while root_str in sys.path:
            sys.path.remove(root_str)
            removed_count += 1
        try:
            mod = _load_coverage_checker()
            assert mod is not None
            assert hasattr(mod, "get_changed_source_files")
            assert root_str not in sys.path  # removed again on the way out
        finally:
            for _ in range(removed_count):
                sys.path.insert(0, root_str)

    def test_loads_the_real_module_when_repo_root_already_on_sys_path(self) -> None:
        root_str = str(ROOT)
        already_present = root_str in sys.path
        if not already_present:
            sys.path.insert(0, root_str)
        try:
            mod = _load_coverage_checker()
            assert mod is not None
        finally:
            if not already_present and root_str in sys.path:
                sys.path.remove(root_str)


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


class TestDeclaredAccounting:
    """Decision 170: every reachable exit path declares an examined count or a skip."""

    @pytest.fixture(autouse=True)
    def _clear_subprocess_guard(self, monkeypatch):
        monkeypatch.delenv("_COVERAGE_SUBPROCESS", raising=False)

    def test_recursion_guard_declares_a_skip(self, monkeypatch) -> None:
        monkeypatch.setenv("_COVERAGE_SUBPROCESS", "1")
        with patch.object(registry, "skipped") as mock_skipped, patch.object(registry, "examined") as mock_examined:
            validate_test_coverage([])
        mock_skipped.assert_called_once()
        mock_examined.assert_not_called()

    def test_checker_absent_declares_a_skip(self) -> None:
        with (
            patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=None),
            patch.object(registry, "skipped") as mock_skipped,
            patch.object(registry, "examined") as mock_examined,
        ):
            validate_test_coverage([])
        mock_skipped.assert_called_once()
        mock_examined.assert_not_called()

    def test_no_source_file_changes_declares_examined_zero(self) -> None:
        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = []
        with (
            patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker),
            patch.object(registry, "examined") as mock_examined,
        ):
            validate_test_coverage([])
        mock_examined.assert_called_once_with(0, unit="source_files")

    def test_real_run_declares_examined_count(self, tmp_path: Path) -> None:
        source = tmp_path / "src" / "config.py"
        source.parent.mkdir(parents=True)
        source.write_text("def foo(): pass", encoding="utf-8")

        mock_checker = MagicMock()
        mock_checker.get_changed_source_files.return_value = [source]
        mock_checker.check_test_file_exists.return_value = (True, "test file found")
        mock_checker.check_per_file_coverage.return_value = []

        with (
            patch("scripts.checks.misc.validate_test_coverage._load_coverage_checker", return_value=mock_checker),
            patch.object(registry, "examined") as mock_examined,
        ):
            validate_test_coverage([])
        mock_examined.assert_called_once_with(1, unit="source_files")
