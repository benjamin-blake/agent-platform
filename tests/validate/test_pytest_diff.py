"""run_pytest_diff() collectability/heavy-dep-deferral tests -- orchestrator residue (rec-2709 Wave 1)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks._scaffolding import (
    _excluded_heavy_import_names,
    _parse_requirement_dist_names,
    partition_changed_tests_by_collectability,
)
from tests.fixtures.validate_module import _validate

run_pytest_diff = _validate.run_pytest_diff


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


class TestFastTierCollectability:
    """Classifier routing: (returncode, output) -> (runnable | deferred) (rec-2485).

    Every heavy-dep-absence case below monkeypatches importlib.util.find_spec because pyarrow
    (and the other heavy deps) are actually installed in this dev venv -- only requirements-fast.txt
    (the pr-validate CI job) omits them, so genuine absence must be simulated here.
    """

    def test_heavy_dep_collection_error_defers(self) -> None:
        """A collect-only error whose root cause is a genuinely-absent excluded-heavy dep defers."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_some_heavy_dep_file.py"])

        assert runnable == []
        assert deferred == [("tests/test_some_heavy_dep_file.py", "pyarrow")]

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

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'scripts.some_deleted_module'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_something.py"])

        assert runnable == ["tests/test_something.py"]
        assert deferred == []

    def test_syntaxerror_collection_error_hard_fails(self) -> None:
        """A collection error with NO 'No module named' line (SyntaxError) routes to runnable, not deferred."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "SyntaxError: invalid syntax"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_broken.py"])

        assert runnable == ["tests/test_broken.py"]
        assert deferred == []

    def test_cannot_import_name_hard_fails(self) -> None:
        """A collection error carrying 'ImportError: cannot import name' (no 'No module named') hard-fails."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ImportError: cannot import name 'Thing' from 'scripts.foo'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_broken_import.py"])

        assert runnable == ["tests/test_broken_import.py"]
        assert deferred == []

    def test_present_module_not_deferred(self) -> None:
        """A ModuleNotFoundError naming an excluded-heavy dep that IS importable (find_spec not None) is not deferred."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_some_heavy_dep_file.py"])

        assert runnable == ["tests/test_some_heavy_dep_file.py"]
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

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 5
            result.stderr = ""
            result.stdout = (
                "collected 0 items / 1 skipped\n\n"
                "=========================== short test summary info ============================\n"
                "SKIPPED [1] tests/test_ops_data_portal.py:33: could not import 'duckdb': "
                "No module named 'duckdb'\n"
                "========================= no tests collected in 0.06s ==========================\n"
            )
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_ops_data_portal.py"])

        assert runnable == []
        assert deferred == [("tests/test_ops_data_portal.py", "duckdb")]

    def test_module_level_importorskip_gate_not_reddened_end_to_end(self) -> None:
        """End-to-end: run_pytest_diff must not append 'Tests (pytest)' to failed when the sole
        changed file defers on a module-level importorskip (rec-2707 CI follow-up)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 5
            result.stderr = ""
            result.stdout = "SKIPPED [1] tests/test_ops_data_portal.py:33: could not import 'duckdb': No module named 'duckdb'"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_data_portal.py"], failed)

        assert failed == []

    def test_iceberg_reader_defers_when_pyarrow_absent(self) -> None:
        """Real-file proof: the actual PR #405 offending file (tests/test_iceberg_reader.py, which
        imports pyarrow at module scope) lands in `deferred`, not `failed`, when pyarrow is simulated
        absent via find_spec."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            if "--collect-only" in cmd:
                result.returncode = 2
                result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            else:
                result.returncode = 0
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            runnable, deferred = partition_changed_tests_by_collectability(["tests/test_iceberg_reader.py"])

        assert runnable == []
        assert deferred == [("tests/test_iceberg_reader.py", "pyarrow")]


class TestRunPytestDiff:
    """Orchestration behaviours of run_pytest_diff() -- the consumer moved out of validate.py (rec-2485)."""

    def test_no_op_when_no_changed_tests(self) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")):
            run_pytest_diff([], failed)
        assert failed == []

    def test_prints_loud_warning_and_does_not_redden_when_all_defer(self, capsys: pytest.CaptureFixture) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = ""
            result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py"], failed)

        captured = capsys.readouterr()
        assert "DEFERRED TO FULL TIER" in captured.out
        assert "tests/test_iceberg_reader.py" in captured.out
        assert "pyarrow" in captured.out
        assert failed == []


class TestRunPytestDiffSingleExecution:
    """Common-case single execution (acceptance criterion 1): when every changed test file
    collects and passes, run_pytest_diff issues EXACTLY ONE non-collect-only pytest invocation
    over the runnable set -- no proactive per-file isolated probe."""

    def test_runs_pytest_exactly_once_in_mixed_case(self) -> None:
        """tests/test_iceberg_reader.py defers at --collect-only (never gets a real run at all);
        tests/test_validate.py collects fine and passes, so it gets exactly one real run."""
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "--collect-only" in cmd:
                if "tests/test_iceberg_reader.py" in cmd:
                    result.returncode = 2
                    result.stderr = "ModuleNotFoundError: No module named 'pyarrow'"
                else:
                    result.returncode = 0
            else:
                result.returncode = 0
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_iceberg_reader.py", "tests/test_validate.py"], failed)

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
