"""Tests for scripts/checks/typing/mypy_baseline.py: baseline load/parse, the mypy-output
parser, the proof-of-execution guard, validate_mypy_ratchet(), validate_mypy_baseline_edits()
(Decision 161 tamper guard), and the --seed/--update CLI modes."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks.typing import mypy_baseline


class TestLoadBaseline:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert mypy_baseline.load_baseline(tmp_path / "nope.yaml") == {}

    def test_loads_entries(self, tmp_path: Path) -> None:
        p = tmp_path / "mypy_baseline.yaml"
        p.write_text("entries:\n  scripts/x.py: 5  # some comment\n", encoding="utf-8")
        assert mypy_baseline.load_baseline(p) == {"scripts/x.py": 5}

    def test_empty_entries_key_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "mypy_baseline.yaml"
        p.write_text("entries: {}\n", encoding="utf-8")
        assert mypy_baseline.load_baseline(p) == {}

    def test_uses_common_root_when_path_omitted(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "mypy_baseline.yaml").write_text("entries:\n  scripts/x.py: 3\n", encoding="utf-8")
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert mypy_baseline.load_baseline() == {"scripts/x.py": 3}


class TestParseEntryLines:
    def test_well_formed_line_with_marker(self) -> None:
        text = "  scripts/x.py: 5  # baseline-raised: dec-161 moved from scripts/old.py\n"
        assert mypy_baseline._parse_entry_lines(text) == {"scripts/x.py": (5, "dec-161")}

    def test_well_formed_line_without_marker(self) -> None:
        text = "  scripts/x.py: 5\n"
        assert mypy_baseline._parse_entry_lines(text) == {"scripts/x.py": (5, None)}

    def test_comment_with_no_marker_match(self) -> None:
        text = "  scripts/x.py: 5  # grandfathered, no marker here\n"
        assert mypy_baseline._parse_entry_lines(text) == {"scripts/x.py": (5, None)}

    def test_blank_and_comment_only_and_entries_key_lines_skipped(self) -> None:
        text = "entries:\n\n# a full-line comment\n  scripts/x.py: 5\n"
        assert mypy_baseline._parse_entry_lines(text) == {"scripts/x.py": (5, None)}

    def test_malformed_line_ignored_not_raised(self) -> None:
        text = "this is not a valid entry line\n  scripts/x.py: 5\n"
        assert mypy_baseline._parse_entry_lines(text) == {"scripts/x.py": (5, None)}


class TestDecisionHeaderExists:
    def test_true_when_header_present(self) -> None:
        assert mypy_baseline._decision_header_exists("dec-161", "## Decision 161: Some title (Decided)\n")

    def test_false_when_header_absent(self) -> None:
        assert not mypy_baseline._decision_header_exists("dec-999", "## Decision 161: Some title (Decided)\n")


class TestParseErrorCounts:
    def test_counts_only_error_lines_and_sums_per_file(self) -> None:
        stdout = (
            "scripts/x.py:10: error: bad type  [assignment]\n"
            'scripts/x.py:11: note: Error code "assignment" not covered by comment\n'
            "scripts/x.py:12: error: another bad type  [assignment]\n"
            "src/y.py:5: error: also bad  [misc]\n"
            "Found 3 errors in 2 files (checked 10 source files)\n"
        )
        assert mypy_baseline._parse_error_counts(stdout) == {"scripts/x.py": 2, "src/y.py": 1}

    def test_found_errors_summary_line_alone_not_miscounted(self) -> None:
        stdout = "Found 5 errors in 3 files (checked 20 source files)\n"
        assert mypy_baseline._parse_error_counts(stdout) == {}

    def test_paths_outside_scripts_and_src_excluded(self) -> None:
        stdout = "tests/test_x.py:1: error: bad  [assignment]\n"
        assert mypy_baseline._parse_error_counts(stdout) == {}

    def test_backslash_normalised(self) -> None:
        stdout = "scripts\\windows\\x.py:1: error: bad  [assignment]\n"
        assert mypy_baseline._parse_error_counts(stdout) == {"scripts/windows/x.py": 1}


class TestRunMypy:
    def test_found_errors_terminator_parses_and_invokes_correctly(self) -> None:
        stdout = "scripts/x.py:1: error: bad  [assignment]\nFound 1 error in 1 file (checked 1 source file)\n"
        mock_result = MagicMock(stdout=stdout)
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            failed: list[str] = []
            result = mypy_baseline._run_mypy(failed)

        assert result == {"scripts/x.py": 1}
        assert failed == []
        called_args, called_kwargs = mock_run.call_args
        assert called_args[0] == [mypy_baseline._common.PYTHON, "-m", "mypy", "scripts/", "src/"]
        assert called_kwargs["cwd"] == mypy_baseline._common.ROOT

    def test_success_terminator_is_legitimate_clean_run_not_conflated_with_failure(self) -> None:
        """PROOF-OF-EXECUTION (ii): a genuinely clean run must pass, not fail."""
        mock_result = MagicMock(stdout="Success: no issues found in 362 source files\n")
        with patch("scripts.checks._common.run", return_value=mock_result):
            failed: list[str] = []
            result = mypy_baseline._run_mypy(failed)

        assert result == {}
        assert failed == []

    def test_neither_terminator_fails_loudly_and_returns_none(self) -> None:
        """PROOF-OF-EXECUTION (i): mypy absent/crashed/misinvoked/output-format-drift must
        never be silently treated as zero errors everywhere -- a distinct loud failure is
        appended and None (not a vacuously-passable {}) is returned."""
        mock_result = MagicMock(stdout="mypy: command not found\n")
        with patch("scripts.checks._common.run", return_value=mock_result):
            failed: list[str] = []
            result = mypy_baseline._run_mypy(failed)

        assert result is None
        assert len(failed) == 1
        assert "proof-of-execution" in failed[0]

    def test_none_stdout_treated_as_empty_and_fails_loudly(self) -> None:
        mock_result = MagicMock(stdout=None)
        with patch("scripts.checks._common.run", return_value=mock_result):
            failed: list[str] = []
            result = mypy_baseline._run_mypy(failed)

        assert result is None
        assert len(failed) == 1


class TestDefaultBaseReader:
    def test_returns_stdout_on_success(self) -> None:
        mock_result = MagicMock(returncode=0, stdout="entries:\n  scripts/x.py: 5\n")
        with patch("scripts.checks._common.run", return_value=mock_result) as mock_run:
            result = mypy_baseline._default_base_reader("config/mypy_baseline.yaml")

        assert result == "entries:\n  scripts/x.py: 5\n"
        assert mock_run.call_args.args[0] == ["git", "show", "origin/main:config/mypy_baseline.yaml"]

    def test_returns_none_on_failure(self) -> None:
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("scripts.checks._common.run", return_value=mock_result):
            result = mypy_baseline._default_base_reader("config/mypy_baseline.yaml")

        assert result is None


class TestValidateMypyRatchet:
    def _write_baseline(self, tmp_path: Path, entries: dict[str, int]) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["entries:"] + [f"  {k}: {v}" for k, v in entries.items()]
        (config_dir / "mypy_baseline.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_measured_equals_baseline_passes(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed, measured={"scripts/x.py": 5})

        assert failed == []

    def test_measured_over_baseline_fails(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed, measured={"scripts/x.py": 6})

        assert len(failed) == 1
        assert "mypy error-count ratchet" in failed[0]

    def test_measured_under_baseline_passes_with_advisory(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed, measured={"scripts/x.py": 2})

        assert failed == []
        assert "ratchet-down advisories" in capsys.readouterr().out

    def test_unregistered_file_with_errors_fails_implicit_zero(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {})
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed, measured={"scripts/new.py": 1})

        assert len(failed) == 1

    def test_unregistered_file_with_zero_errors_passes(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {})
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed, measured={})

        assert failed == []

    def test_baseline_entry_now_clean_does_not_fail(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed, measured={"scripts/x.py": 0})

        assert failed == []

    def test_measured_omitted_calls_run_mypy(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", return_value={"scripts/x.py": 5}) as mock_run_mypy,
        ):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed)

        assert failed == []
        mock_run_mypy.assert_called_once()

    def test_run_mypy_none_short_circuits_without_crash_or_false_pass_messaging(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """When _run_mypy's proof-of-execution guard fires (appends to failed, returns None),
        validate_mypy_ratchet must return immediately -- never iterate a per-file comparison
        against a None measurement (which would crash) or print pass/advisory messaging that
        would suggest the run was clean."""
        self._write_baseline(tmp_path, {"scripts/x.py": 5})

        def fake_run_mypy(failed_list: list[str]) -> None:
            failed_list.append("mypy proof-of-execution guard: fake failure")
            return None

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", side_effect=fake_run_mypy),
        ):
            failed: list[str] = []
            mypy_baseline.validate_mypy_ratchet(failed)

        assert failed == ["mypy proof-of-execution guard: fake failure"]
        out = capsys.readouterr().out
        assert "No mypy error-count regressions" not in out
        assert "ratchet-down advisories" not in out


class TestValidateMypyBaselineEdits:
    def _write_current(self, tmp_path: Path, body: str) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "mypy_baseline.yaml").write_text(body, encoding="utf-8")

    def _write_decisions(self, tmp_path: Path, decision_numbers: list[int]) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(exist_ok=True)
        text = "\n".join(f"## Decision {n}: Some title (Decided)\n" for n in decision_numbers)
        (docs_dir / "DECISIONS.md").write_text(text, encoding="utf-8")

    def test_fails_on_unmarked_raise(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 10\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 5\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert len(failed) == 1
        assert "mypy baseline tamper guard" in failed[0]

    def test_passes_raise_with_valid_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 10  # baseline-raised: dec-161 regression, tracked\n")
        self._write_decisions(tmp_path, [161])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 5\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_fails_marker_citing_nonexistent_decision(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 10  # baseline-raised: dec-999 bogus\n")
        self._write_decisions(tmp_path, [161])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 5\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_fails_new_registration_without_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/new.py: 3\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries: {}\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert len(failed) == 1

    def test_passes_new_registration_with_marker(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/new.py: 3  # baseline-raised: dec-161 moved from scripts/old.py\n")
        self._write_decisions(tmp_path, [161])
        base_reader = lambda rel: "entries: {}\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_decrease_unmarked(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 5\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 10\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_passes_removal_unmarked(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries: {}\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: "entries:\n  scripts/x.py: 10\n"  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_skips_when_base_reader_returns_none(self, tmp_path: Path) -> None:
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 10\n")
        self._write_decisions(tmp_path, [])
        base_reader = lambda rel: None  # noqa: E731

        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=base_reader)

        assert failed == []

    def test_no_current_file_returns_early_without_failing(self, tmp_path: Path) -> None:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed, base_reader=lambda rel: "entries: {}\n")

        assert failed == []

    def test_default_base_reader_used_when_omitted(self, tmp_path: Path) -> None:
        """Proves the `reader = base_reader or _default_base_reader` wire-up."""
        self._write_current(tmp_path, "entries:\n  scripts/x.py: 5\n")
        self._write_decisions(tmp_path, [])
        mock_result = MagicMock(returncode=0, stdout="entries:\n  scripts/x.py: 5\n")
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=mock_result),
        ):
            failed: list[str] = []
            mypy_baseline.validate_mypy_baseline_edits(failed)

        assert failed == []


class TestSeed:
    def test_seed_writes_initial_roster_for_files_with_at_least_one_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "config").mkdir()
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.typing.mypy_baseline._run_mypy",
                return_value={"scripts/x.py": 3, "scripts/clean.py": 0},
            ),
        ):
            rc = mypy_baseline._seed()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert rc == 0
        assert result == {"scripts/x.py": 3}
        assert "Seeded 1 entries totalling 3 errors" in capsys.readouterr().out

    def test_seed_refuses_when_baseline_already_exists(self, tmp_path: Path) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "mypy_baseline.yaml").write_text("entries:\n  scripts/x.py: 1\n", encoding="utf-8")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy") as mock_run_mypy,
        ):
            rc = mypy_baseline._seed()

        assert rc == 1
        mock_run_mypy.assert_not_called()

    def test_seed_aborts_when_mypy_did_not_run_to_completion(self, tmp_path: Path) -> None:
        def fake_run_mypy(failed: list[str]) -> None:
            failed.append("mypy proof-of-execution guard: fake failure")
            return None

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", side_effect=fake_run_mypy),
        ):
            rc = mypy_baseline._seed()

        assert rc == 1
        assert not (tmp_path / "config" / "mypy_baseline.yaml").exists()


class TestUpdate:
    def _write_baseline(self, tmp_path: Path, entries: dict[str, int]) -> None:
        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        lines = ["entries:"] + [f"  {k}: {v}" for k, v in entries.items()]
        (config_dir / "mypy_baseline.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_lowers_improved_entry(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 10})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", return_value={"scripts/x.py": 4}),
        ):
            rc = mypy_baseline._update()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert rc == 0
        assert result == {"scripts/x.py": 4}

    def test_drops_now_clean_file(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 10})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", return_value={"scripts/x.py": 0}),
        ):
            mypy_baseline._update()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert "scripts/x.py" not in result

    def test_drops_deleted_file(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 10})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", return_value={}),
        ):
            mypy_baseline._update()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert result == {}

    def test_never_raises_an_entry(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", return_value={"scripts/x.py": 9}),
        ):
            mypy_baseline._update()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert result == {"scripts/x.py": 5}

    def test_never_seeds_a_newly_dirty_unregistered_file(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.typing.mypy_baseline._run_mypy",
                return_value={"scripts/x.py": 5, "scripts/newly_dirty.py": 7},
            ),
        ):
            mypy_baseline._update()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert "scripts/newly_dirty.py" not in result

    def test_against_absent_roster_writes_nothing(self, tmp_path: Path) -> None:
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy") as mock_run_mypy,
        ):
            rc = mypy_baseline._update()

        assert rc == 0
        assert not (tmp_path / "config" / "mypy_baseline.yaml").exists()
        mock_run_mypy.assert_not_called()

    def test_against_empty_roster_writes_nothing(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {})
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy") as mock_run_mypy,
        ):
            rc = mypy_baseline._update()

        assert rc == 0
        mock_run_mypy.assert_not_called()

    def test_update_aborts_when_mypy_did_not_run_to_completion(self, tmp_path: Path) -> None:
        self._write_baseline(tmp_path, {"scripts/x.py": 5})

        def fake_run_mypy(failed: list[str]) -> None:
            failed.append("mypy proof-of-execution guard: fake failure")
            return None

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.typing.mypy_baseline._run_mypy", side_effect=fake_run_mypy),
        ):
            rc = mypy_baseline._update()
            result = mypy_baseline.load_baseline(tmp_path / "config" / "mypy_baseline.yaml")

        assert rc == 1
        assert result == {"scripts/x.py": 5}  # untouched


class TestMain:
    def test_seed_flag_dispatches_to_seed(self) -> None:
        with patch("scripts.checks.typing.mypy_baseline._seed", return_value=0) as mock_seed:
            rc = mypy_baseline.main(["--seed"])

        assert rc == 0
        mock_seed.assert_called_once()

    def test_update_flag_dispatches_to_update(self) -> None:
        with patch("scripts.checks.typing.mypy_baseline._update", return_value=0) as mock_update:
            rc = mypy_baseline.main(["--update"])

        assert rc == 0
        mock_update.assert_called_once()

    def test_requires_exactly_one_mode(self) -> None:
        with pytest.raises(SystemExit):
            mypy_baseline.main([])

    def test_mutually_exclusive_modes_rejected(self) -> None:
        with pytest.raises(SystemExit):
            mypy_baseline.main(["--seed", "--update"])
