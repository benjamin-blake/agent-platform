"""Tests for test_coverage_checker.main() -- the argparse CLI entrypoint.

New module (Decision 128/130: every tests/ file is SLOC-gated, so new coverage goes in a new
module rather than growing a moved one). Drives main() across its flag matrix with patched argv
and patched collaborator functions (get_changed_source_files / check_test_file_exists /
check_per_file_coverage), asserting exit codes and the printed summary lines. Per this package's
conftest.py, subprocess.Popen is patched to raise by default -- these tests never need a real
coverage subprocess since check_per_file_coverage is monkeypatched directly in every case.
"""

from pathlib import Path

import pytest

from tests.fixtures.coverage_checker_module import ROOT, checker

main = checker.main


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(checker.sys, "argv", ["test_coverage_checker.py", *argv])
    with pytest.raises(SystemExit) as excinfo:
        main()
    return excinfo.value.code


class TestMainNoFlags:
    def test_no_flags_prints_help_and_exits_zero(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        code = _run_main(monkeypatch, [])
        assert code == 0
        out = capsys.readouterr().out
        assert "usage" in out.lower()


class TestMainNoChangedFiles:
    def test_check_tests_with_no_changed_files_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [])
        code = _run_main(monkeypatch, ["--check-tests"])
        assert code == 0
        assert "No source file changes to check." in capsys.readouterr().out


class TestMainCheckTests:
    def test_check_tests_all_present_exits_zero(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        src = ROOT / "scripts" / "fake_module_for_main_cli_test.py"
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [src])
        monkeypatch.setattr(checker, "check_test_file_exists", lambda _p: (True, "test file found"))
        code = _run_main(monkeypatch, ["--check-tests"])
        out = capsys.readouterr().out
        assert code == 0
        assert "all 1 source files have test files" in out
        assert "DIAGNOSTIC VERDICT: PASS" in out

    def test_check_tests_missing_exits_one(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        src = ROOT / "scripts" / "fake_module_for_main_cli_test.py"
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [src])
        monkeypatch.setattr(checker, "check_test_file_exists", lambda _p: (False, "missing test file: tests/test_x.py"))
        code = _run_main(monkeypatch, ["--check-tests"])
        out = capsys.readouterr().out
        assert code == 1
        assert "Missing test files:" in out
        assert "missing test file: tests/test_x.py" in out
        assert "DIAGNOSTIC VERDICT: FAIL" in out


class TestMainCheckCoverage:
    def test_check_coverage_all_at_100_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        src = ROOT / "scripts" / "fake_module_for_main_cli_test.py"
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [src])
        monkeypatch.setattr(checker, "check_per_file_coverage", lambda _files: [])
        code = _run_main(monkeypatch, ["--check-coverage"])
        out = capsys.readouterr().out
        assert code == 0
        assert "all 1 source files at 100%" in out
        assert "DIAGNOSTIC VERDICT: PASS" in out

    def test_check_coverage_below_threshold_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        src = ROOT / "scripts" / "fake_module_for_main_cli_test.py"
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [src])
        monkeypatch.setattr(
            checker,
            "check_per_file_coverage",
            lambda _files: ["scripts/fake_module_for_main_cli_test.py: 50.0% line coverage"],
        )
        code = _run_main(monkeypatch, ["--check-coverage"])
        out = capsys.readouterr().out
        assert code == 1
        assert "Coverage failures (< 100%):" in out
        assert "50.0% line coverage" in out
        assert "DIAGNOSTIC VERDICT: FAIL" in out


class TestMainBothFlags:
    def test_both_flags_combines_both_error_sections(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        src = ROOT / "scripts" / "fake_module_for_main_cli_test.py"
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [src])
        monkeypatch.setattr(checker, "check_test_file_exists", lambda _p: (False, "missing test file: tests/test_x.py"))
        monkeypatch.setattr(checker, "check_per_file_coverage", lambda _files: ["x.py: 10.0% line coverage"])
        code = _run_main(monkeypatch, ["--check-tests", "--check-coverage"])
        out = capsys.readouterr().out
        assert code == 1
        assert "Missing test files:" in out
        assert "Coverage failures (< 100%):" in out

    def test_both_flags_all_pass_exits_zero(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        src = ROOT / "scripts" / "fake_module_for_main_cli_test.py"
        monkeypatch.setattr(checker, "get_changed_source_files", lambda files=None: [src])
        monkeypatch.setattr(checker, "check_test_file_exists", lambda _p: (True, "test file found"))
        monkeypatch.setattr(checker, "check_per_file_coverage", lambda _files: [])
        code = _run_main(monkeypatch, ["--check-tests", "--check-coverage"])
        assert code == 0
        out = capsys.readouterr().out
        assert "Test coverage check: 1 source files checked, 0 missing test files, 0 below 100% coverage" in out


class TestMainFilesFlag:
    def test_files_flag_is_forwarded_to_get_changed_source_files(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, list[str] | None] = {}

        def fake_get_changed_source_files(files: list[str] | None = None) -> list[Path]:
            captured["files"] = files
            return []

        monkeypatch.setattr(checker, "get_changed_source_files", fake_get_changed_source_files)
        _run_main(monkeypatch, ["--check-tests", "--files", "scripts/a.py", "scripts/b.py"])
        assert captured["files"] == ["scripts/a.py", "scripts/b.py"]
