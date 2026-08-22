"""Coverage-instrumentation + deferral-map tests for scripts/checks/_pytest_diff.py
(PLAN-premerge-diff-coverage-gate). Decision 128 sibling of tests/validate/test_pytest_diff.py --
that file's SLOC headroom is thin (35 lines against the 500 budget at this plan's landing), so
this NEW concern (coverage artifact + deferral-map state classification) lives in its own module
rather than pushing test_pytest_diff.py over budget."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.checks._pytest_diff import (
    STATE_ALL_DEFERRED,
    STATE_EMPTY_AFFECTED_SET,
    STATE_OK,
    STATE_TWO_INVOCATION_FAILURE,
    _write_deferral_map,
    run_pytest_diff,
)


def _collect_error_block(path: str, missing_module: str) -> str:
    return (
        f"__________________ ERROR collecting {path} ___________________\n"
        f"E   ModuleNotFoundError: No module named '{missing_module}'\n"
    )


class TestDeferralMapStateClassification:
    """The three no-usable-artifact states, plus the ordinary OK state, are each classified via
    the deferral-map write -- not silently conflated (this plan's core acceptance surface)."""

    def test_empty_affected_set_writes_that_state(self) -> None:
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=AssertionError("run must not be called")),
        ):
            run_pytest_diff([], [])
        mock_write.assert_called_once_with(STATE_EMPTY_AFFECTED_SET, {})

    def test_all_files_deferred_writes_that_state(self) -> None:
        test_file = "tests/test_heavy.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 2
            result.stdout = _collect_error_block(test_file, "pyarrow")
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([test_file], [])
        mock_write.assert_called_once_with(STATE_ALL_DEFERRED, {test_file: "pyarrow"})

    def test_clean_pass_writes_ok_state(self) -> None:
        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            run_pytest_diff(["tests/test_a.py"], [])
        mock_write.assert_called_once_with(STATE_OK, {})

    def test_genuine_single_invocation_failure_still_writes_ok_state(self) -> None:
        """A hard failure with NO heavy-dep signature is still exactly ONE invocation -- its
        coverage.json remains a usable snapshot of that one run."""

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0 if "--collect-only" in cmd else 1
            result.stdout = "FAILED tests/test_a.py::test_x - AssertionError"
            result.stderr = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
        ):
            run_pytest_diff(["tests/test_a.py"], failed)
        mock_write.assert_called_once_with(STATE_OK, {})
        assert failed == ["Tests (pytest)"]

    def test_reactive_fallback_writes_two_invocation_failure_state(self) -> None:
        """Primary run fails on a heavy-dep signature and a second invocation runs on the
        survivor set -- the deferral map must classify this as TWO_INVOCATION_FAILURE, not OK,
        even though the second invocation itself passes."""
        runnable_file = "tests/test_lazy_heavy.py"

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            result = MagicMock()
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            elif "-v" in cmd and runnable_file in cmd and "--cov=src" in cmd:
                # primary traced invocation: fails with a lazily-imported heavy dep signature
                result.returncode = 1
                result.stdout = (
                    f"FAILED {runnable_file}::test_x - ModuleNotFoundError\n"
                    "E   ModuleNotFoundError: No module named 'pyarrow'\n"
                )
                result.stderr = ""
            else:
                # isolated per-file probe, or the reactive survivor re-run
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        failed: list[str] = []
        with (
            patch("scripts.checks._pytest_diff._write_deferral_map") as mock_write,
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([runnable_file], failed)

        mock_write.assert_called_once_with(STATE_TWO_INVOCATION_FAILURE, {})
        assert failed == []


class TestWriteDeferralMapLoudSkip:
    def test_oserror_on_write_prints_loud_skip_never_raises(self, tmp_path, capsys) -> None:
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            _write_deferral_map(STATE_OK, {}, root=tmp_path)
        out = capsys.readouterr().out
        assert "loud skip" in out
        assert "disk full" in out


class TestPrimaryInvocationCarriesCoverageFlags:
    def test_primary_invocation_has_explicit_cov_fail_under_zero(self) -> None:
        """Live-measured (VP step 2): a directory-scoped run measures well under pyproject.toml's
        fail_under=37 -- --cov-fail-under=0 at the invocation site must override it, never a
        [tool.coverage.report] re-baseline."""
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(cmd))
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        with patch("scripts.checks._common.run", side_effect=mock_run):
            run_pytest_diff(["tests/test_a.py"], [])

        real_run = next(c for c in captured if "--collect-only" not in c)
        assert "--cov=src" in real_run
        assert "--cov=scripts" in real_run
        assert "--cov-fail-under=0" in real_run
        assert any(flag.startswith("--cov-report=json:") for flag in real_run)

    def test_reactive_survivor_rerun_carries_no_cov_flags(self) -> None:
        """The declared green-path lever: only the primary invocation is traced, never the
        reactive survivor re-run."""
        runnable_file = "tests/test_lazy_heavy.py"
        captured: list[list[str]] = []

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured.append(list(cmd))
            result = MagicMock()
            if "--collect-only" in cmd:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            elif "--cov=src" in cmd:
                result.returncode = 1
                result.stdout = f"FAILED {runnable_file}::test_x\nE   ModuleNotFoundError: No module named 'pyarrow'\n"
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        with (
            patch("scripts.checks._common.run", side_effect=mock_run),
            patch("importlib.util.find_spec", return_value=None),
        ):
            run_pytest_diff([runnable_file], [])

        traced = [c for c in captured if "--collect-only" not in c and "--cov=src" in c]
        # "-v" distinguishes the real reactive re-run from the isolated per-file probe (a separate
        # "-q" single-file subprocess that also names runnable_file but is not the re-run itself).
        untraced_reruns = [
            c for c in captured if "--collect-only" not in c and "--cov=src" not in c and "-v" in c and runnable_file in c
        ]
        assert len(traced) == 1
        assert len(untraced_reruns) == 1
        assert not any(flag.startswith("--cov") for flag in untraced_reruns[0])
