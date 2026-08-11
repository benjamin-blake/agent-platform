"""Fast-tier budget assertion / ignore-budget-flag tests -- orchestrator residue (rec-2709 Wave 1)."""

import itertools
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import registry
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate

# All of the below are still reachable on the "validate" module object -- retained
# _common/_scaffolding re-exports (scripts/validate.py:42-61) or module-local constants/helpers,
# unaffected by Decision 169's check-facade deletion.
get_changed_files = _validate.get_changed_files
_file_budget_breach_rec = _validate._file_budget_breach_rec
_file_budget_bypass_rec = _validate._file_budget_bypass_rec
_mirror_budget_notice_to_summary = _validate._mirror_budget_notice_to_summary
_FAST_TIER_BUDGET_SECONDS = _validate._FAST_TIER_BUDGET_SECONDS
_FORCED_FULL_SUITE_CEILING_SECONDS = _validate._FORCED_FULL_SUITE_CEILING_SECONDS
run_pytest_diff = _validate.run_pytest_diff


class TestBudgetAssertion:
    """Tests for the 5-minute fast-tier wall-clock budget assertion."""

    def test_exits_1_on_budget_breach(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 1

    def test_budget_breach_output_contains_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("validate._file_budget_breach_rec"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        captured = capsys.readouterr()
        assert "Fast tier exceeded budget" in captured.out

    def test_exits_0_within_budget(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0

    def test_budget_constant_is_300(self) -> None:
        assert _FAST_TIER_BUDGET_SECONDS == 300

    def test_breach_rec_receives_a_real_dominant_phase(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """The dominant phase threaded to _file_budget_breach_rec must correctly identify WHICH
        step actually dominated the elapsed wall-clock -- not merely be non-None. Makes
        pytest_diff artificially slow (a real, attributable jump in the mocked clock) relative to
        every other near-zero step, so the assertion is on correctness of attribution, not just
        truthiness."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def slow_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
            clock["t"] += 1000.0  # dwarfs every other (near-zero) step's duration

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch("validate.run_pytest_diff", side_effect=slow_pytest_diff),
            patch("time.monotonic", side_effect=fake_monotonic),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        dominant_phase_arg = mock_breach.call_args[0][2]
        assert dominant_phase_arg == "pytest_diff"

    def test_breach_console_error_names_dominant_phase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        """Same correctness bar as above, applied to the printed console diagnostic."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        clock = {"t": 0.0}

        def fake_monotonic() -> float:
            return clock["t"]

        def slow_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
            clock["t"] += 1000.0

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("validate._file_budget_breach_rec"),
            patch("validate.run_pytest_diff", side_effect=slow_pytest_diff),
            patch("time.monotonic", side_effect=fake_monotonic),
            pytest.raises(SystemExit),
        ):
            _validate.main()

        captured = capsys.readouterr()
        assert "Dominant phase: pytest_diff" in captured.out


class TestForcedFullSuiteWaiver:
    """Decision 153: a root-conftest-forced full-suite --pre run warns-and-passes instead of
    hard-failing, bounded by a forced-run ceiling derived from the pr-validate job timeout.
    Every non-forced breach keeps EXACTLY today's hard-fail (Decision 73 anti-drift intact).

    full_suite_forced is injected by patching scripts.checks.deps.affected_tests.derive_affected_tests
    / emit_manifest -- the function-scope import seam validate.py's --pre block uses (Decision
    affected-set-selection); real derivation is exercised by the affected_tests test suite itself.
    """

    @staticmethod
    def _selection(forced: bool) -> dict:
        return {"selected": [], "manifest": {"full_suite_forced": forced}}

    def test_forced_breach_within_ceiling_warns_and_passes(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=self._selection(True)),
            patch("scripts.checks.deps.affected_tests.emit_manifest"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_breach.assert_not_called()

    def test_waiver_notice_is_distinct(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=self._selection(True)),
            patch("scripts.checks.deps.affected_tests.emit_manifest"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "budget waived: full-suite scope forced by root-conftest change" in captured.out
        assert "Fast tier exceeded budget" not in captured.out

    def test_non_forced_breach_still_hard_fails(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=self._selection(False)),
            patch("scripts.checks.deps.affected_tests.emit_manifest"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 1
        mock_breach.assert_called_once()

    def test_forced_breach_at_exactly_ceiling_warns_and_passes(
        self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=self._selection(True)),
            patch("scripts.checks.deps.affected_tests.emit_manifest"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch(
                "time.monotonic",
                side_effect=itertools.chain([0.0], itertools.repeat(float(_FORCED_FULL_SUITE_CEILING_SECONDS))),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_breach.assert_not_called()

    def test_forced_breach_over_ceiling_hard_fails(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, pre_sequence_stub
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("scripts.checks.deps.affected_tests.derive_affected_tests", return_value=self._selection(True)),
            patch("scripts.checks.deps.affected_tests.emit_manifest"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            patch(
                "time.monotonic",
                side_effect=itertools.chain([0.0], itertools.repeat(float(_FORCED_FULL_SUITE_CEILING_SECONDS) + 100.0)),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 1
        mock_breach.assert_not_called()
        captured = capsys.readouterr()
        assert "ceiling" in captured.out.lower()


class TestIgnoreBudgetFlag:
    """Tests for the --ignore-budget escape hatch."""

    def test_bypass_calls_bypass_rec_helper(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_bypass.assert_called_once()

    def test_bypass_reason_captured_when_provided(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget", "--ignore-budget-reason", "disk slow"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit),
        ):
            _validate.main()

        reason_arg = mock_bypass.call_args[0][2]
        assert reason_arg == "disk slow"

    def test_bypass_reason_null_when_omitted(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec") as mock_bypass,
            pytest.raises(SystemExit),
        ):
            _validate.main()

        reason_arg = mock_bypass.call_args[0][2]
        assert reason_arg is None

    def test_bypass_skips_budget_assertion(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        """Breach rec is NOT filed when --ignore-budget is set, even if elapsed > 300."""
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(400.0))),
            patch("validate._file_budget_bypass_rec"),
            patch("validate._file_budget_breach_rec") as mock_breach,
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0
        mock_breach.assert_not_called()


class TestIgnoreBudgetCIGuard:
    """Tests for the CI guard that forbids --ignore-budget in CI environments."""

    def test_refuses_ignore_budget_in_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _validate.main()

        assert exc_info.value.code == 1

    def test_ci_guard_message_contains_expected_phrase(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with pytest.raises(SystemExit):
            _validate.main()

        captured = capsys.readouterr()
        assert "cannot be used in CI" in captured.out

    def test_allows_ignore_budget_when_ci_not_set(self, monkeypatch: pytest.MonkeyPatch, pre_sequence_stub) -> None:
        monkeypatch.setattr(sys, "argv", ["validate", "--pre", "--ignore-budget"])
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.run", side_effect=_pre_mock_run),
            patch.object(registry, "pre_sequence", return_value=pre_sequence_stub(checks=())),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(60.0))),
            patch("validate._file_budget_bypass_rec"),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0


class TestBudgetBreachCiTelemetry:
    """CI-native budget-breach telemetry (pre-validation-performance / rec-2387): with
    CI="true" and GITHUB_STEP_SUMMARY set, _file_budget_breach_rec writes dominant_phase +
    the diff manifest to that file, files no rec, and stages no outbox entry."""

    def test_writes_dominant_phase_and_manifest_to_step_summary(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CI", "true")
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _file_budget_breach_rec(400.0, ["scripts/validate.py", "tests/test_validate.py"], "pytest_diff")

        content = summary_file.read_text(encoding="utf-8")
        assert "pytest_diff" in content
        assert "scripts/validate.py" in content
        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_no_ops_outbox_staged(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CI", "true")
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        outbox_dir = tmp_path / "logs" / ".ops-outbox"

        with patch("scripts.checks._common.run") as mock_run:
            _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        mock_run.assert_not_called()
        assert not outbox_dir.exists()

    def test_falls_back_to_stderr_when_step_summary_unset(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("CI", "true")
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        _file_budget_breach_rec(400.0, ["scripts/validate.py"], "pytest_diff")

        captured = capsys.readouterr()
        assert "pytest_diff" in captured.err


class TestForcedWaiverCiTelemetry:
    """Decision 153: the forced-waiver/-ceiling notice helper mirrors a titled section to
    GITHUB_STEP_SUMMARY and files no rec (it has no ops_data_portal path at all) -- mirrors
    TestBudgetBreachCiTelemetry's pattern for the pre-existing breach-rec helper."""

    def test_mirrors_titled_section_and_files_no_rec(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        summary_file = tmp_path / "step-summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        mock_portal = MagicMock()

        with (
            patch("scripts.checks._common.run") as mock_run,
            patch.dict(sys.modules, {"scripts.ops_data_portal": mock_portal}),
        ):
            _mirror_budget_notice_to_summary(
                "Fast-tier budget waived (forced full-suite scope)",
                "budget waived: full-suite scope forced by root-conftest change.",
            )

        content = summary_file.read_text(encoding="utf-8")
        assert "Fast-tier budget waived (forced full-suite scope)" in content
        assert "budget waived: full-suite scope forced by root-conftest change." in content
        mock_portal.file_rec.assert_not_called()
        mock_run.assert_not_called()

    def test_falls_back_to_print_when_step_summary_unset(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

        _mirror_budget_notice_to_summary("Fast-tier forced-run ceiling breached", "some distinct ceiling message")

        captured = capsys.readouterr()
        assert "some distinct ceiling message" in captured.out
