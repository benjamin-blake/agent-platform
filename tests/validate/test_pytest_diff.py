"""run_pytest_diff() collectability/heavy-dep-deferral tests -- orchestrator residue (rec-2709
Wave 1), updated for the batched single-invocation collect-only partition (Decision
affected-set-selection: ~30x fewer collect-only subprocess spawns than the prior
one-call-per-file loop)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks._scaffolding import (
    _excluded_heavy_import_names,
    _match_changed_test_path,
    _parse_requirement_dist_names,
    partition_changed_tests_by_collectability,
)
from tests.fixtures.validate_module import _validate

run_pytest_diff = _validate.run_pytest_diff


def _collect_error_block(path: str, missing_module: str) -> str:
    """A realistic `ERROR collecting <path>` block, matching pytest's actual --collect-only
    output shape (verified empirically) -- one such block per uncollectable file."""
    return (
        f"__________________ ERROR collecting {path} ___________________\n"
        f"ImportError while importing test module '/fake/repo/{path}'.\n"
        "Hint: make sure your test modules/packages have valid Python names.\n"
        "Traceback:\n"
        f"{path}:1: in <module>\n"
        f"    import {missing_module}\n"
        f"E   ModuleNotFoundError: No module named '{missing_module}'\n"
    )


def _skipped_line(path: str, missing_module: str, line: int = 2) -> str:
    """A realistic `-rs` SKIPPED summary line for a module-level pytest.importorskip guard."""
    return f"SKIPPED [1] {path}:{line}: could not import '{missing_module}': No module named '{missing_module}'\n"


class TestExcludedHeavyDeps:
    """Excluded-heavy import-name set derivation from the REAL requirements files (rec-2485)."""

    def test_heavy_deps_in_excluded_set(self) -> None:
        excluded = _excluded_heavy_import_names()
        for name in ("pyarrow", "pandas", "numpy", "duckdb"):
            assert name in excluded, f"{name} should be excluded (heavy, requirements.txt-only)"

    def test_fast_tier_deps_not_in_excluded_set(self) -> None:
        excluded = _excluded_heavy_import_names()
        for name in ("ruff", "mypy", "pytest", "pyyaml", "pydantic"):
            assert name not in excluded, f"{name} is present in requirements-fast.txt; must not be excluded"

    def test_parse_requirement_dist_names_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        assert _parse_requirement_dist_names(tmp_path / "nonexistent-requirements.txt") == set()


class TestMatchChangedTestPath:
    """Direct coverage of _match_changed_test_path's exact/suffix/no-match branches."""

    def test_exact_match(self) -> None:
        assert _match_changed_test_path("tests/test_a.py", ["tests/test_a.py", "tests/test_b.py"]) == "tests/test_a.py"

    def test_suffix_match_for_absolute_or_rootdir_variant(self) -> None:
        assert _match_changed_test_path("/repo/tests/test_a.py", ["tests/test_a.py"]) == "tests/test_a.py"

    def test_no_match_returns_none(self) -> None:
        assert _match_changed_test_path("tests/test_unrelated.py", ["tests/test_a.py"]) is None


class TestBatchedCollectOnlyInvocation:
    """The partition runs as a SINGLE batched pytest --collect-only invocation, never one
    subprocess per file (Decision affected-set-selection, VP step 11)."""

    def test_single_invocation_for_multiple_files(self) -> None:
        calls: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            calls.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            partition_changed_tests_by_collectability(["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"])

        assert len(calls) == 1, f"expected exactly one collect-only subprocess call, got {len(calls)}"
        cmd = calls[0]
        assert "tests/test_a.py" in cmd
        assert "tests/test_b.py" in cmd
        assert "tests/test_c.py" in cmd

    def test_empty_changed_tests_makes_no_call(self) -> None:
        with patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")):
            runnable, deferred = partition_changed_tests_by_collectability([])
        assert runnable == []
        assert deferred == []


class TestMixedBatchAttribution:
    """A MIXED batch (one uncollectable file + several runnable ones) defers ONLY the
    uncollectable file and runs the rest -- under the single batched invocation (VP step 11)."""

    def test_mixed_batch_defers_only_the_bad_file(self) -> None:
        good_files = ["tests/test_good_a.py", "tests/test_good_b.py"]
        bad_file = "tests/test_bad_heavy.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(bad_file, "pyarrow")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([*good_files, bad_file])

        assert sorted(runnable) == sorted(good_files)
        assert deferred == [(bad_file, "pyarrow")]

    def test_two_distinct_bad_files_both_attributed(self) -> None:
        good_file = "tests/test_good.py"
        bad_file_1 = "tests/test_bad_1.py"
        bad_file_2 = "tests/test_bad_2.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(bad_file_1, "pyarrow") + _collect_error_block(bad_file_2, "duckdb")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([good_file, bad_file_1, bad_file_2])

        assert runnable == [good_file]
        assert dict(deferred) == {bad_file_1: "pyarrow", bad_file_2: "duckdb"}


class TestFastTierCollectability:
    """Classifier routing: (collect-only signal for THIS file) -> (runnable | deferred) (rec-2485).

    Every heavy-dep-absence case below monkeypatches importlib.util.find_spec because pyarrow
    (and the other heavy deps) are actually installed in this dev venv -- only requirements-fast.txt
    (the pr-validate CI job) omits them, so genuine absence must be simulated here.
    """

    def test_heavy_dep_collection_error_defers(self) -> None:
        """A collect-only error whose root cause is a genuinely-absent excluded-heavy dep defers."""
        test_file = "tests/test_some_heavy_dep_file.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "pyarrow")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == []
        assert deferred == [(test_file, "pyarrow")]

    def test_runtime_failure_hard_fails(self) -> None:
        """A file that collects fine but fails at runtime (pytest exit 1) still hard-fails the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0 if "--collect-only" in cmd else 1
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_something.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_non_heavy_modulenotfound_routes_to_runnable(self) -> None:
        """A collection error naming a repo-local (non-excluded) module routes to runnable."""
        test_file = "tests/test_something.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "scripts.some_deleted_module")
            result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == [test_file]
        assert deferred == []

    def test_syntaxerror_collection_error_hard_fails(self) -> None:
        """A collection error with NO 'No module named' line (SyntaxError) routes to runnable, not deferred."""
        test_file = "tests/test_broken.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = (
                f"__________________ ERROR collecting {test_file} ___________________\n"
                f"{test_file}:3: SyntaxError: invalid syntax\n"
            )
            result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == [test_file]
        assert deferred == []

    def test_cannot_import_name_hard_fails(self) -> None:
        """A collection error carrying 'ImportError: cannot import name' (no 'No module named') hard-fails."""
        test_file = "tests/test_broken_import.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = (
                f"__________________ ERROR collecting {test_file} ___________________\n"
                "E   ImportError: cannot import name 'Thing' from 'scripts.foo'\n"
            )
            result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == [test_file]
        assert deferred == []

    def test_present_module_not_deferred(self) -> None:
        """A ModuleNotFoundError naming an excluded-heavy dep that IS importable (find_spec not None) is not deferred."""
        test_file = "tests/test_some_heavy_dep_file.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "pyarrow")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == [test_file]
        assert deferred == []

    def test_collect_only_passes_rs_flag(self) -> None:
        """`-rs` must be in the --collect-only invocation -- without it, a module-level
        pytest.importorskip's skip reason (which carries the 'No module named' signature) never
        appears in captured output, and the file is misrouted to runnable (rec-2707 CI follow-up)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run) as mock_common_run:
            partition_changed_tests_by_collectability(["tests/test_something.py"])

        collect_only_cmd = mock_common_run.call_args[0][0]
        assert "-rs" in collect_only_cmd

    def test_module_level_importorskip_defers_not_runnable(self) -> None:
        """A module-level `pytest.importorskip("duckdb")` guard makes --collect-only exit 5
        (NO_TESTS_COLLECTED, a graceful skip -- not a collection error) with the skip reason
        only visible via -rs. This must defer, not route to runnable (rec-2707 CI follow-up:
        tests/test_ops_data_portal.py hit this when it was the sole changed test file -- the
        real run then collected 0 distributable items under -n auto and reddened the gate)."""
        test_file = "tests/test_ops_data_portal.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 5
            result.stderr = ""
            result.stdout = (
                "collected 0 items / 1 skipped\n\n"
                "=========================== short test summary info ============================\n"
                f"{_skipped_line(test_file, 'duckdb', line=33)}"
                "========================= no tests collected in 0.06s ==========================\n"
            )
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == []
        assert deferred == [(test_file, "duckdb")]

    def test_module_level_importorskip_gate_not_reddened_end_to_end(self) -> None:
        """End-to-end: run_pytest_diff must not append 'Tests (pytest)' to failed when the sole
        changed file defers on a module-level importorskip (rec-2707 CI follow-up)."""
        test_file = "tests/test_ops_data_portal.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 5
            result.stderr = ""
            result.stdout = _skipped_line(test_file, "duckdb", line=33)
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([test_file], failed)

        assert failed == []

    def test_module_level_importorskip_alongside_good_file_returncode_zero(self) -> None:
        """A self-skipping file alongside at least one good file in the SAME batch exits 0
        overall (verified empirically) -- per-file SKIPPED-line attribution must still fire
        even when the batch's overall returncode is 0, not gated on nonzero."""
        good_file = "tests/test_good.py"
        skip_file = "tests/test_ops_data_portal.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            result.stdout = _skipped_line(skip_file, "duckdb", line=33)
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([good_file, skip_file])

        assert runnable == [good_file]
        assert deferred == [(skip_file, "duckdb")]

    def test_iceberg_reader_defers_when_pyarrow_absent(self) -> None:
        """Real-file proof: the actual PR #405 offending file (tests/test_iceberg_reader.py, which
        imports pyarrow at module scope) lands in `deferred`, not `failed`, when pyarrow is simulated
        absent via find_spec."""
        test_file = "tests/test_iceberg_reader.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "pyarrow")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability([test_file])

        assert runnable == []
        assert deferred == [(test_file, "pyarrow")]


class TestRunPytestDiff:
    """Orchestration behaviours of run_pytest_diff() -- the consumer moved out of validate.py (rec-2485)."""

    def test_no_op_when_no_changed_tests(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")):
            run_pytest_diff([], failed)
        assert failed == []

    def test_prints_loud_warning_and_does_not_redden_when_all_defer(self, capsys: pytest.CaptureFixture) -> None:
        test_file = "tests/test_iceberg_reader.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "pyarrow")
            result.stderr = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([test_file], failed)

        captured = capsys.readouterr()
        assert "DEFERRED TO FULL TIER" in captured.out
        assert test_file in captured.out
        assert "pyarrow" in captured.out
        assert failed == []


class TestRunPytestDiffSingleExecution:
    """Common-case single execution (acceptance criterion 1): when every changed test file
    collects and passes, run_pytest_diff issues EXACTLY ONE non-collect-only pytest invocation
    over the runnable set, fed by EXACTLY ONE batched --collect-only invocation -- no proactive
    per-file isolated probe, no per-file collect-only subprocess."""

    def test_runs_pytest_exactly_once_in_mixed_case(self) -> None:
        """tests/test_iceberg_reader.py defers at --collect-only (never gets a real run at all);
        tests/test_validate.py collects fine and passes, so it gets exactly one real run --
        both resolved from a SINGLE batched --collect-only invocation."""
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stdout = _collect_error_block("tests/test_iceberg_reader.py", "pyarrow")
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py", "tests/test_validate.py"], failed)

        collect_only_cmds = [c for c in captured_cmds if "--collect-only" in c]
        assert len(collect_only_cmds) == 1, f"expected exactly one collect-only invocation, got: {collect_only_cmds}"
        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1, f"expected exactly one real pytest run, got: {real_run_cmds}"
        assert "tests/test_validate.py" in real_run_cmds[0]
        assert "tests/test_iceberg_reader.py" not in real_run_cmds[0]
        assert failed == []

    def test_runs_pytest_exactly_once_when_all_runnable_pass(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            result.returncode = 0
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_a.py", "tests/test_b.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1, f"expected exactly one real pytest run, got: {real_run_cmds}"
        assert "tests/test_a.py" in real_run_cmds[0]
        assert "tests/test_b.py" in real_run_cmds[0]
        assert failed == []
