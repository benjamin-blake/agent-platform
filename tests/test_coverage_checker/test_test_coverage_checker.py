"""Mirror home (flat rule) for scripts/test_coverage_checker.py.

Uses the shared singleton loader (tests/fixtures/coverage_checker_module.py) so
`patch("test_coverage_checker.<name>")` intercepts the SAME module object every other
tests/test_coverage_checker_*.py file resolves against -- see that fixture's docstring.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures.coverage_checker_module import ROOT, checker

get_changed_source_files = checker.get_changed_source_files
measure_per_file_coverage = checker.measure_per_file_coverage
check_per_file_coverage = checker.check_per_file_coverage


class TestGetChangedSourceFilesPushContextBase:
    """get_changed_source_files() consuming scripts.checks._common.push_context_base()."""

    def test_uses_push_context_base_when_non_none(self, tmp_path: Path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        mock_diff = MagicMock(returncode=0, stdout="scripts/foo.py\n")

        with (
            patch("scripts.checks._common.push_context_base", return_value="deadbeef"),
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.subprocess.run", return_value=mock_diff) as mock_run,
        ):
            result = get_changed_source_files()

        assert any("foo.py" in str(p) for p in result)
        called = mock_run.call_args.args[0]
        assert called == ["git", "diff", "--name-only", "deadbeef"]

    def test_falls_back_to_merge_base_when_none(self, tmp_path: Path) -> None:
        """push_context_base() returning None keeps today's merge-base-or-HEAD block verbatim."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bar.py").write_text("x = 1\n", encoding="utf-8")
        mock_merge_base = MagicMock(returncode=0, stdout="abc123\n")
        mock_diff = MagicMock(returncode=0, stdout="src/bar.py\n")

        with (
            patch("scripts.checks._common.push_context_base", return_value=None),
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.subprocess.run", side_effect=[mock_merge_base, mock_diff]) as mock_run,
        ):
            result = get_changed_source_files()

        assert any("bar.py" in str(p) for p in result)
        # second call is the merge-base-diff, unaffected by the push-context branch
        assert mock_run.call_args_list[1].args[0] == ["git", "diff", "--name-only", "abc123"]


class TestMeasurePerFileCoverageEntryPoint:
    """measure_per_file_coverage() is the same measurement mechanism check_per_file_coverage()
    consumes -- an observability requirement so a caller (e.g. a VP anti-vacuity check) can
    assert the gate produced a REAL numeric result rather than a silent no-op."""

    def test_measure_per_file_coverage_reports_same_number_as_check(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text('{"files": {"scripts/probe.py": {"summary": {"percent_covered": 87.7}}}}', encoding="utf-8")

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_file),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
        ):
            pcts = measure_per_file_coverage([source])

        assert pcts == {str(source.resolve()): 87.7}

    def test_unmeasured_file_reports_none_not_missing_key(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "orphan.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=None),
        ):
            pcts = measure_per_file_coverage([source])

        assert pcts == {}


class TestCheckPerFileCoverageBaselineAware:
    """check_per_file_coverage()'s baseline-aware pass/fail semantics (Decision 130 style)."""

    def test_unbaselined_file_fails_below_100(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text('{"files": {"scripts/probe.py": {"summary": {"percent_covered": 90.0}}}}', encoding="utf-8")

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_file),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
            patch("scripts.checks.misc.coverage_baseline.load_baseline", return_value={}),
        ):
            errors = check_per_file_coverage([source])

        assert errors and "expected 100%" in errors[0]

    def test_baselined_file_passes_below_100_when_meets_entry(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)
        (test_dir / "test_write_paths.py").write_text("# test", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text(
            '{"files": {"scripts/ops_writer.py": {"summary": {"percent_covered": 75.5}}}}', encoding="utf-8"
        )

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
            patch("scripts.checks.misc.coverage_baseline.load_baseline", return_value={"scripts/ops_writer.py": 75.4}),
        ):
            errors = check_per_file_coverage([source])

        assert errors == []

    def test_baselined_file_fails_when_below_entry(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)
        (test_dir / "test_write_paths.py").write_text("# test", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text(
            '{"files": {"scripts/ops_writer.py": {"summary": {"percent_covered": 70.0}}}}', encoding="utf-8"
        )

        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")

        with (
            patch("test_coverage_checker.ROOT", tmp_path),
            patch("test_coverage_checker.map_source_to_test", return_value=test_dir),
            patch("test_coverage_checker.subprocess.Popen", return_value=proc),
            patch("scripts.checks.misc.coverage_baseline.load_baseline", return_value={"scripts/ops_writer.py": 75.4}),
        ):
            errors = check_per_file_coverage([source])

        assert len(errors) == 1
        assert "expected >= 75.4%" in errors[0]


def test_root_and_extract_definitions_are_reachable() -> None:
    """Sanity: the shared fixture singleton exposes ROOT / extract_definitions unchanged."""
    assert ROOT.is_dir()
    assert checker.extract_definitions(ROOT / "scripts" / "test_coverage_checker.py") is not None
