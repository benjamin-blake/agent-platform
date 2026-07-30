"""Tests for scripts/checks/misc/coverage_baseline.py: load/compare, the measurement engine,
and validate_coverage_baseline_edits() (Decision 128 mirror tamper guard)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.misc import coverage_baseline


class TestLoadBaseline:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert coverage_baseline.load_baseline(tmp_path / "nope.yaml") == {}

    def test_loads_entries_rounded_to_one_decimal(self, tmp_path: Path) -> None:
        p = tmp_path / "coverage_baseline.yaml"
        p.write_text(
            "entries:\n  scripts/ops_writer.py: 75.4601  # grandfathered dec-159 (one-time roster)\n", encoding="utf-8"
        )
        assert coverage_baseline.load_baseline(p) == {"scripts/ops_writer.py": 75.5}

    def test_empty_entries_key_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "coverage_baseline.yaml"
        p.write_text("entries: {}\n", encoding="utf-8")
        assert coverage_baseline.load_baseline(p) == {}


class TestCompare:
    def test_passes_at_or_above_baseline(self) -> None:
        assert coverage_baseline.compare(75.5, "scripts/ops_writer.py", {"scripts/ops_writer.py": 75.4})
        assert coverage_baseline.compare(75.4, "scripts/ops_writer.py", {"scripts/ops_writer.py": 75.4})

    def test_fails_below_baseline(self) -> None:
        assert not coverage_baseline.compare(75.0, "scripts/ops_writer.py", {"scripts/ops_writer.py": 75.4})

    def test_unbaselined_file_requires_100(self) -> None:
        assert not coverage_baseline.compare(99.9, "scripts/unbaselined.py", {})
        assert coverage_baseline.compare(100.0, "scripts/unbaselined.py", {})

    def test_uses_load_baseline_when_table_omitted(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "coverage_baseline.yaml").write_text("entries:\n  scripts/x.py: 50.0\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert coverage_baseline.compare(50.0, "scripts/x.py")
            assert not coverage_baseline.compare(49.0, "scripts/x.py")


class TestMeasureAndCheck:
    """Drives the measurement engine directly with injected root/map_source_to_test/is_empty_dir/
    subprocess_module -- this is what lets scripts/test_coverage_checker.py's own module-globals
    (patchable via `patch("test_coverage_checker.<name>")`) remain the sole source of truth for
    the legacy split test suite while the heavy loop body lives here (SLOC decompose)."""

    def test_returns_none_when_test_target_unmapped(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "orphan.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")

        pcts, errors = coverage_baseline.measure_and_check(
            [source],
            root=tmp_path,
            map_source_to_test=lambda p: None,
            is_empty_dir=lambda p: False,
            subprocess_module=MagicMock(),
        )
        assert pcts == {}
        assert errors == []

    def test_returns_none_for_empty_directory_target(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "ops_writer.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_dir = tmp_path / "tests" / "ops_writer"
        test_dir.mkdir(parents=True)

        mock_subprocess = MagicMock()
        pcts, errors = coverage_baseline.measure_and_check(
            [source],
            root=tmp_path,
            map_source_to_test=lambda p: test_dir,
            is_empty_dir=lambda p: True,
            subprocess_module=mock_subprocess,
        )
        assert pcts == {}
        assert errors == []
        mock_subprocess.Popen.assert_not_called()

    def test_measures_matched_file_pct(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text('{"files": {"scripts/probe.py": {"summary": {"percent_covered": 87.7}}}}', encoding="utf-8")

        mock_subprocess = MagicMock()
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")
        mock_subprocess.Popen.return_value = proc

        pcts, errors = coverage_baseline.measure_and_check(
            [source],
            root=tmp_path,
            map_source_to_test=lambda p: test_file,
            is_empty_dir=lambda p: False,
            subprocess_module=mock_subprocess,
        )
        assert pcts == {str(source.resolve()): 87.7}
        assert errors == []
        called_cmd = mock_subprocess.Popen.call_args.args[0]
        cov_args = [a for a in called_cmd if isinstance(a, str) and a.startswith("--cov=")]
        assert cov_args == ["--cov=scripts"], called_cmd

    def test_unmatched_report_yields_none_and_error(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        coverage_json = tmp_path / ".coverage.json"
        coverage_json.write_text(
            '{"files": {"scripts/unrelated.py": {"summary": {"percent_covered": 100.0}}}}', encoding="utf-8"
        )

        mock_subprocess = MagicMock()
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")
        mock_subprocess.Popen.return_value = proc

        pcts, errors = coverage_baseline.measure_and_check(
            [source],
            root=tmp_path,
            map_source_to_test=lambda p: test_file,
            is_empty_dir=lambda p: False,
            subprocess_module=mock_subprocess,
        )
        assert pcts == {str(source.resolve()): None}
        assert any("0% coverage" in e for e in errors)

    def test_missing_coverage_json_yields_none_no_error(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        mock_subprocess = MagicMock()
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")
        mock_subprocess.Popen.return_value = proc

        pcts, errors = coverage_baseline.measure_and_check(
            [source],
            root=tmp_path,
            map_source_to_test=lambda p: test_file,
            is_empty_dir=lambda p: False,
            subprocess_module=mock_subprocess,
        )
        assert pcts == {str(source.resolve()): None}
        assert errors == []

    def test_source_path_outside_root_is_skipped(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "not_under_root.py"
        outside.write_text("x = 1\n", encoding="utf-8")

        pcts, errors = coverage_baseline.measure_and_check(
            [outside],
            root=tmp_path,
            map_source_to_test=lambda p: None,
            is_empty_dir=lambda p: False,
            subprocess_module=MagicMock(),
        )
        assert pcts == {}
        assert errors == []

    def test_malformed_coverage_json_yields_none(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        (tmp_path / ".coverage.json").write_text("{not valid json", encoding="utf-8")

        mock_subprocess = MagicMock()
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")
        mock_subprocess.Popen.return_value = proc

        pcts, errors = coverage_baseline.measure_and_check(
            [source],
            root=tmp_path,
            map_source_to_test=lambda p: test_file,
            is_empty_dir=lambda p: False,
            subprocess_module=mock_subprocess,
        )
        assert pcts == {str(source.resolve()): None}
        assert errors == []

    def test_unlink_oserror_is_swallowed(self, tmp_path: Path) -> None:
        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        (tmp_path / ".coverage.json").write_text(
            '{"files": {"scripts/probe.py": {"summary": {"percent_covered": 100.0}}}}', encoding="utf-8"
        )

        mock_subprocess = MagicMock()
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.return_value = ("", "")
        mock_subprocess.Popen.return_value = proc

        with patch("pathlib.Path.unlink", side_effect=OSError("locked")):
            pcts, errors = coverage_baseline.measure_and_check(
                [source],
                root=tmp_path,
                map_source_to_test=lambda p: test_file,
                is_empty_dir=lambda p: False,
                subprocess_module=mock_subprocess,
            )
        assert pcts == {str(source.resolve()): 100.0}
        assert errors == []

    def test_timeout_yields_none_and_error(self, tmp_path: Path) -> None:
        import subprocess as real_subprocess

        source = tmp_path / "scripts" / "probe.py"
        source.parent.mkdir(parents=True)
        source.write_text("x = 1\n", encoding="utf-8")
        test_file = tmp_path / "tests" / "test_probe.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# test\n", encoding="utf-8")

        mock_subprocess = MagicMock()
        mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
        mock_subprocess.PIPE = real_subprocess.PIPE
        proc = MagicMock()
        proc.__enter__.return_value = proc
        proc.__exit__.return_value = False
        proc.communicate.side_effect = real_subprocess.TimeoutExpired(cmd="pytest", timeout=300)
        proc.pid = 12345
        mock_subprocess.Popen.return_value = proc

        with patch("scripts.llm.utils.kill_process_tree") as mock_kill:
            pcts, errors = coverage_baseline.measure_and_check(
                [source],
                root=tmp_path,
                map_source_to_test=lambda p: test_file,
                is_empty_dir=lambda p: False,
                subprocess_module=mock_subprocess,
            )
        mock_kill.assert_called_once_with(12345)
        assert pcts == {str(source.resolve()): None}
        assert any("timed out" in e for e in errors)


class TestDefaultBaseReader:
    def test_returns_stdout_on_success(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="entries:\n  scripts/x.py: 80.0\n")
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            result = coverage_baseline._default_base_reader("config/coverage_baseline.yaml")
        assert result == "entries:\n  scripts/x.py: 80.0\n"
        assert mock_run.call_args.args[0] == ["git", "show", "origin/main:config/coverage_baseline.yaml"]

    def test_returns_none_on_failure(self) -> None:
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("scripts.checks._common.run", return_value=mock_result):
            result = coverage_baseline._default_base_reader("config/coverage_baseline.yaml")
        assert result is None


class TestValidateCoverageBaselineEdits:
    def _write_current(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "coverage_baseline.yaml").write_text(body, encoding="utf-8")

    def _write_decisions(self, tmp_path: Path, decision_numbers: list[int]) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(exist_ok=True)
        text = "\n".join(f"## Decision {n}: Some title (Decided)\n" for n in decision_numbers)
        (docs_dir / "DECISIONS.md").write_text(text, encoding="utf-8")

    def test_skips_when_base_absent(self, tmp_path: Path) -> None:
        """Missing-base (e.g. this plan's own seeding PR) SKIPs -- never 'missing == empty'."""
        self._write_current(tmp_path, "entries:\n  scripts/new.py: 80.0  # grandfathered dec-159 (one-time roster)\n")
        self._write_decisions(tmp_path, [])

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=lambda rel: None)

        assert failed == []

    def test_fails_on_unmarked_lowering(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 60.0\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 80.0\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert len(failed) == 1
        assert "Coverage baseline tamper guard" in failed[0]

    def test_passes_lowering_with_valid_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 60.0  # baseline-lowered: dec-159 regression, tracked\n")
        self._write_decisions(tmp_path, [159])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 80.0\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_fails_lowering_marker_cites_nonexistent_decision(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 60.0  # baseline-lowered: dec-999 bogus\n")
        self._write_decisions(tmp_path, [159])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 80.0\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_fails_new_sub100_registration_without_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/new.py: 90.0\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries: {}\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_passes_new_sub100_registration_with_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/new.py: 90.0  # baseline-lowered: dec-159 newly discovered debt\n")
        self._write_decisions(tmp_path, [159])
        base_reader = lambda rel: "entries: {}\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_on_raise(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 90.0\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 60.0\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_on_removal(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries: {}\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 60.0\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_no_current_file_is_noop(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            coverage_baseline.validate_coverage_baseline_edits(failed, base_reader=lambda rel: "entries: {}\n")

        assert failed == []
