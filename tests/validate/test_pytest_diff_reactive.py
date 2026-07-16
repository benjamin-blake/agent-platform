"""run_pytest_diff() reactive-defer / parallel-and-timeout / pinned-seed tests -- orchestrator residue (rec-2709 Wave 1)."""

import re
import sys
from unittest.mock import MagicMock, patch

from scripts.checks._scaffolding import _PYTEST_FLAGS
from tests.fixtures.validate_module import _validate

ROOT = _validate.ROOT
run_pytest_diff = _validate.run_pytest_diff


class TestRunPytestDiffReactiveDefer:
    """Reactive lazy-import heavy-dep defer (acceptance criterion 2): a genuinely-absent
    excluded heavy dependency imported lazily (function scope, invisible to --collect-only) is
    caught only AFTER the combined run fails, via a per-file isolated re-classification pass
    (rec-2572..2576 test_ops_writer.py shape). Every other failure shape reddens immediately."""

    def test_runtime_lazy_import_of_excluded_dep_defers(self) -> None:
        """A file that collects fine but fails at real-run time with a genuinely-absent excluded
        dep defers, via the reactive per-file probe -- and does not redden the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_ops_writer.py::TestCompact::test_compact_x - "
                    "ModuleNotFoundError: No module named 'pandas'\n"
                )
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == []

    def test_runtime_failure_with_no_module_error_reddens_immediately(self) -> None:
        """A file that collects fine and fails at runtime with no 'No module named' signature at
        all is a genuine failure -- must redden immediately (fail-closed), with no reactive re-run."""
        real_run_calls = {"n": 0}

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stdout = ""
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
            else:
                real_run_calls["n"] += 1
                result.returncode = 1
            return result

        failed: list[str] = []
        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_something.py"], failed)

        assert failed == ["Tests (pytest)"]
        assert real_run_calls["n"] == 1, "no reactive re-run should occur when there is no heavy-dep signature"

    def test_runtime_knockon_failures_still_defer_whole_file(self) -> None:
        """When one failing test names the missing excluded dep and OTHER failures in the same
        combined run look unrelated (e.g. state-pollution knock-on effects from the first
        failure), the whole file still defers -- ANY match is sufficient, not ALL, because once
        a required dependency is known absent, the other failures in that same run aren't
        independently meaningful."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_ops_writer.py::A::test_a - assert 0 == 1\n"
                    "FAILED tests/test_ops_writer.py::B::test_b - "
                    "ModuleNotFoundError: No module named 'pandas'\n"
                    "FAILED tests/test_ops_writer.py::C::test_c - TypeError: 'NoneType' object is not subscriptable\n"
                )
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == []

    def test_runtime_lazy_import_of_present_dep_not_deferred(self) -> None:
        """A runtime ModuleNotFoundError naming an excluded dep that IS actually importable
        (find_spec not None) is a genuine failure, not a fast-tier absence -- must redden, not defer."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            else:
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=MagicMock()),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_reactive_rerun_reddens_on_survivor_failure(self) -> None:
        """Two changed files: one's combined-run failure resolves (via the isolated probe) to a
        genuine failure (survivor), the other to a heavy-dep defer. The survivor is re-run alone;
        a real failure there still reddens the gate."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif "-q" in cmd:
                # isolated per-file probe (_runtime_heavy_dep_defer_reason)
                if "tests/test_a.py" in cmd:
                    result.returncode = 1
                    result.stdout = "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
                else:
                    result.returncode = 1
                    result.stdout = "FAILED tests/test_b.py::test_y - ModuleNotFoundError: No module named 'pandas'\n"
            elif "tests/test_b.py" in cmd:
                # combined gate run: both files present, mixed failure signature
                result.returncode = 1
                result.stdout = (
                    "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
                    "FAILED tests/test_b.py::test_y - ModuleNotFoundError: No module named 'pandas'\n"
                )
            else:
                # reactive re-run of the survivor alone: genuine failure persists
                result.returncode = 1
                result.stdout = "FAILED tests/test_a.py::test_x - assert 0 == 1\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_a.py", "tests/test_b.py"], failed)

        assert failed == ["Tests (pytest)"]

    def test_isolated_probe_passing_makes_file_a_survivor(self) -> None:
        """A file whose combined-run failure carries a heavy-dep signature (triggering the
        reactive fallback) but whose ISOLATED single-file run actually passes (e.g. the failure
        was a cross-file interaction, not a real heavy-dep absence) is treated as a survivor, not
        deferred -- covers _runtime_heavy_dep_defer_reason's rc==0 -> None branch via the reactive
        path specifically (as opposed to the collect-only-only tests in TestFastTierCollectability)."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif "-q" in cmd:
                # isolated probe: passes cleanly in isolation
                result.returncode = 0
                result.stdout = ""
            else:
                # combined run and final survivor re-run both fail identically
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        assert failed == ["Tests (pytest)"]


class TestPytestDiffParallelAndTimeout:
    """run_pytest_diff wires -n (parallel) and --timeout on both pytest invocations
    (pre-validation-performance / rec-2387)."""

    def test_primary_invocation_carries_parallel_and_timeout_flags(self) -> None:
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
            run_pytest_diff(["tests/test_a.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) == 1
        cmd = real_run_cmds[0]
        assert "-n" in cmd
        assert cmd[cmd.index("-n") + 1] == "auto"
        assert "--timeout" in cmd
        assert failed == []

    def test_reactive_rerun_invocation_carries_parallel_and_timeout_flags(self) -> None:
        captured_cmds: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_cmds.append(list(cmd))
            result = MagicMock()
            result.stderr = ""
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
            elif len([c for c in captured_cmds if "--collect-only" not in c]) == 1:
                # the initial (non--collect-only) combined run: fail with a
                # deliberately-excluded, genuinely-absent heavy-dep signature so the
                # reactive re-run path fires
                result.returncode = 1
                result.stdout = "FAILED tests/test_ops_writer.py::A::test_a - ModuleNotFoundError: No module named 'pandas'\n"
            else:
                result.returncode = 0
                result.stdout = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff(["tests/test_ops_writer.py"], failed)

        real_run_cmds = [c for c in captured_cmds if "--collect-only" not in c]
        assert len(real_run_cmds) >= 2, f"expected at least primary + reactive rerun, got: {captured_cmds}"
        rerun_cmd = real_run_cmds[-1]
        assert "-n" in rerun_cmd
        assert rerun_cmd[rerun_cmd.index("-n") + 1] == "auto"
        assert "--timeout" in rerun_cmd
        assert failed == []


class TestPytestFlagsPinnedSeed:
    """rec-2653: _PYTEST_FLAGS pins a fixed integer --randomly-seed so all -n auto xdist
    workers agree on collection order, instead of relying on pyproject.toml's addopts
    '--randomly-seed=last' (which resolves inconsistently across workers on a cold cache)."""

    def test_pytest_flags_pin_fixed_seed(self) -> None:
        seeds = [f for f in _PYTEST_FLAGS if f.startswith("--randomly-seed")]
        assert len(seeds) == 1, _PYTEST_FLAGS
        assert re.fullmatch(r"--randomly-seed=\d+", seeds[0]), seeds[0]

    def test_pinned_seed_reaches_pytest_at_runtime(self) -> None:
        import subprocess

        pin = [f for f in _PYTEST_FLAGS if f.startswith("--randomly-seed")][0].split("=")[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/validate/test_pytest_diff_reactive.py::TestPytestFlagsPinnedSeed::test_pytest_flags_pin_fixed_seed",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                *_PYTEST_FLAGS,
                "--collect-only",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        combined = result.stdout + result.stderr
        match = re.search(r"randomly-seed[:= ]+(\d+)", combined)
        assert match and match.group(1) == pin, combined[-600:]
