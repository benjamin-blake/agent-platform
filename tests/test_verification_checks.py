"""Tests for scripts/verification_checks.py -- typed checks kernel (CD.29).

Coverage: all six primitive slots (PASS and FAIL cases), closed-vocabulary guard
(SLOT_COUNT == 6, file_presence pair counts once), and the differential admission gate.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.verification_checks import (  # noqa: E402
    ALL_CHECK_TYPES,
    CANONICAL_SLOTS,
    SLOT_COUNT,
    BaseCheck,
    CheckResult,
    CheckStatus,
    CommandExitZeroCheck,
    CommandOutputMatchesCheck,
    FileAbsentCheck,
    FileExistsCheck,
    GrepCountCheck,
    MetricUnderThresholdCheck,
    TestSelectorCheck,
    is_admitted,
)

# ---------------------------------------------------------------------------
# Closed-vocabulary guard
# ---------------------------------------------------------------------------


class TestClosedVocabularyGuard:
    def test_slot_count_is_six(self) -> None:
        assert SLOT_COUNT == 6

    def test_canonical_slots_contents(self) -> None:
        expected = {
            "command_exit_zero",
            "command_output_matches",
            "file_presence",
            "grep_count",
            "test_selector",
            "metric_under_threshold",
        }
        assert CANONICAL_SLOTS == expected

    def test_file_presence_pair_shares_one_slot(self) -> None:
        slots = {cls.__dataclass_fields__["slot"].default for cls in ALL_CHECK_TYPES}  # type: ignore[attr-defined]
        assert len(slots) == 6

    def test_seven_classes_six_slots(self) -> None:
        assert len(ALL_CHECK_TYPES) == 7
        assert SLOT_COUNT == 6

    def test_file_exists_and_absent_share_file_presence(self) -> None:
        fe = FileExistsCheck(name="x")
        fa = FileAbsentCheck(name="y")
        assert fe.slot == "file_presence"
        assert fa.slot == "file_presence"


# ---------------------------------------------------------------------------
# Slot 1: command_exit_zero
# ---------------------------------------------------------------------------


class TestCommandExitZeroCheck:
    def test_pass_on_zero_exit(self) -> None:
        check = CommandExitZeroCheck(name="t", command=["true"])
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stderr="", stdout=""),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_fail_on_nonzero_exit(self) -> None:
        check = CommandExitZeroCheck(name="t", command=["false"])
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=1, stderr="error msg", stdout=""),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL
        assert "1" in result.message

    def test_slot(self) -> None:
        assert CommandExitZeroCheck(name="x").slot == "command_exit_zero"


# ---------------------------------------------------------------------------
# Slot 2: command_output_matches
# ---------------------------------------------------------------------------


class TestCommandOutputMatchesCheck:
    def test_exact_match_pass(self) -> None:
        check = CommandOutputMatchesCheck(name="t", command=["echo", "hello"], expected="hello")
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="hello\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_exact_match_fail(self) -> None:
        check = CommandOutputMatchesCheck(name="t", command=["echo", "world"], expected="hello")
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="world\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_regex_match_pass(self) -> None:
        check = CommandOutputMatchesCheck(name="t", command=["echo", "foo123"], expected=r"foo\d+", use_regex=True)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="foo123\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_regex_match_fail(self) -> None:
        check = CommandOutputMatchesCheck(name="t", command=["echo", "bar"], expected=r"foo\d+", use_regex=True)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="bar\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_slot(self) -> None:
        assert CommandOutputMatchesCheck(name="x").slot == "command_output_matches"


# ---------------------------------------------------------------------------
# Slot 3: file_presence
# ---------------------------------------------------------------------------


class TestFileExistsCheck:
    def test_pass_when_file_exists(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            check = FileExistsCheck(name="t", path=tmp.name)
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_fail_when_file_absent(self) -> None:
        check = FileExistsCheck(name="t", path="/nonexistent/path/file.txt")
        result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_slot(self) -> None:
        assert FileExistsCheck(name="x").slot == "file_presence"


class TestFileAbsentCheck:
    def test_pass_when_file_absent(self) -> None:
        check = FileAbsentCheck(name="t", path="/nonexistent/path/file.txt")
        result = check.run()
        assert result.status == CheckStatus.PASS

    def test_fail_when_file_exists(self) -> None:
        with tempfile.NamedTemporaryFile() as tmp:
            check = FileAbsentCheck(name="t", path=tmp.name)
            result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_slot(self) -> None:
        assert FileAbsentCheck(name="x").slot == "file_presence"


# ---------------------------------------------------------------------------
# Slot 4: grep_count
# ---------------------------------------------------------------------------


class TestGrepCountCheck:
    def _make_tmp(self, content: str) -> str:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(content)
            return f.name

    def test_eq_pass(self) -> None:
        path = self._make_tmp("foo\nfoo\nbar\n")
        check = GrepCountCheck(name="t", path=path, pattern="foo", operator="eq", count=2)
        result = check.run()
        Path(path).unlink(missing_ok=True)
        assert result.status == CheckStatus.PASS

    def test_eq_fail(self) -> None:
        path = self._make_tmp("foo\nbar\n")
        check = GrepCountCheck(name="t", path=path, pattern="foo", operator="eq", count=2)
        result = check.run()
        Path(path).unlink(missing_ok=True)
        assert result.status == CheckStatus.FAIL

    def test_gt_pass(self) -> None:
        path = self._make_tmp("a\na\na\n")
        check = GrepCountCheck(name="t", path=path, pattern="a", operator="gt", count=1)
        result = check.run()
        Path(path).unlink(missing_ok=True)
        assert result.status == CheckStatus.PASS

    def test_gte_pass(self) -> None:
        path = self._make_tmp("x\nx\n")
        check = GrepCountCheck(name="t", path=path, pattern="x", operator="gte", count=2)
        result = check.run()
        Path(path).unlink(missing_ok=True)
        assert result.status == CheckStatus.PASS

    def test_lt_pass(self) -> None:
        path = self._make_tmp("y\n")
        check = GrepCountCheck(name="t", path=path, pattern="y", operator="lt", count=5)
        result = check.run()
        Path(path).unlink(missing_ok=True)
        assert result.status == CheckStatus.PASS

    def test_lte_pass(self) -> None:
        path = self._make_tmp("z\nz\n")
        check = GrepCountCheck(name="t", path=path, pattern="z", operator="lte", count=2)
        result = check.run()
        Path(path).unlink(missing_ok=True)
        assert result.status == CheckStatus.PASS

    def test_missing_file(self) -> None:
        check = GrepCountCheck(name="t", path="/no/such/file.txt", pattern="x", operator="eq", count=0)
        result = check.run()
        assert result.status == CheckStatus.FAIL
        assert "not found" in result.message

    def test_slot(self) -> None:
        assert GrepCountCheck(name="x").slot == "grep_count"


# ---------------------------------------------------------------------------
# Slot 5: test_selector
# ---------------------------------------------------------------------------


class TestTestSelectorCheck:
    def test_pass_on_green_pytest(self) -> None:
        node = "tests/test_verification_checks.py::TestClosedVocabularyGuard::test_slot_count_is_six"
        check = TestSelectorCheck(name="t", node_id=node)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="1 passed", stderr=""),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_fail_on_red_pytest(self) -> None:
        check = TestSelectorCheck(name="t", node_id="tests/test_verification_checks.py::Nonexistent")
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=1, stdout="FAILED", stderr=""),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_slot(self) -> None:
        assert TestSelectorCheck(name="x").slot == "test_selector"


def test_test_selector_surfaces_full_failure_output() -> None:
    """rec-2655: the FAIL CheckResult carries the full combined stdout+stderr, not a
    stdout-or-stderr 500-char slice, so the graduation layer can see a "found no
    collectors" collection-error signature even when both streams are non-empty."""
    check = TestSelectorCheck(name="t", node_id="tests/test_ops_data_portal.py::Something::test_x")
    with mock.patch(
        "scripts.verification_checks.subprocess.run",
        return_value=mock.Mock(
            returncode=2,
            stdout="collected 0 items / 1 error\n",
            stderr="ERROR: found no collectors for tests/test_ops_data_portal.py::Something::test_x\n",
        ),
    ):
        result = check.run()
    assert result.status == CheckStatus.FAIL
    assert "collected 0 items / 1 error" in result.actual
    assert "found no collectors" in result.actual


# ---------------------------------------------------------------------------
# Slot 6: metric_under_threshold
# ---------------------------------------------------------------------------


class TestMetricUnderThresholdCheck:
    def test_pass_below_threshold(self) -> None:
        check = MetricUnderThresholdCheck(name="t", command=["echo", "0.5"], threshold=1.0)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="0.5\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_fail_at_threshold(self) -> None:
        check = MetricUnderThresholdCheck(name="t", command=["echo", "1.0"], threshold=1.0)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="1.0\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_fail_above_threshold(self) -> None:
        check = MetricUnderThresholdCheck(name="t", command=["echo", "2.5"], threshold=1.0)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="2.5\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL

    def test_fail_non_numeric(self) -> None:
        check = MetricUnderThresholdCheck(name="t", command=["echo", "not-a-number"], threshold=1.0)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="not-a-number\n"),
        ):
            result = check.run()
        assert result.status == CheckStatus.FAIL
        assert "parse" in result.message

    def test_slot(self) -> None:
        assert MetricUnderThresholdCheck(name="x").slot == "metric_under_threshold"


# ---------------------------------------------------------------------------
# Differential admission gate
# ---------------------------------------------------------------------------


class TestDifferentialAdmissionGate:
    def _make_check(self) -> FileExistsCheck:
        return FileExistsCheck(name="gate-test", path="/some/path")

    def test_admitted_when_revert_fails(self) -> None:
        check = self._make_check()
        revert_runner = lambda c: CheckResult(status=CheckStatus.FAIL, message="pre-change: absent")  # noqa: E731
        assert is_admitted(check, revert_runner) is True

    def test_not_admitted_when_revert_passes(self) -> None:
        check = self._make_check()
        revert_runner = lambda c: CheckResult(status=CheckStatus.PASS)  # noqa: E731
        assert is_admitted(check, revert_runner) is False

    def test_revert_runner_receives_check(self) -> None:
        received: list[BaseCheck] = []
        check = self._make_check()

        def revert_runner(c: BaseCheck) -> CheckResult:
            received.append(c)
            return CheckResult(status=CheckStatus.FAIL)

        is_admitted(check, revert_runner)
        assert received == [check]


# ---------------------------------------------------------------------------
# VP selector hooks -- standalone functions named so that
# `pytest -k <selector>` collects at least one test.
# ---------------------------------------------------------------------------


def test_closed_vocabulary_slot_count_is_six() -> None:
    """VP step 2: closed-vocabulary guard asserts exactly 6 slots."""
    assert SLOT_COUNT == 6
    slots = {cls.__dataclass_fields__["slot"].default for cls in ALL_CHECK_TYPES}  # type: ignore[attr-defined]
    assert slots == CANONICAL_SLOTS
    assert len(slots) == 6


def test_differential_admission_gate_admits_on_revert_fail() -> None:
    """VP step 7: differential admission gate -- admitted iff revert produces FAIL."""
    check = FileExistsCheck(name="vp7-check", path="/some/path")
    assert is_admitted(check, lambda c: CheckResult(status=CheckStatus.FAIL)) is True
    assert is_admitted(check, lambda c: CheckResult(status=CheckStatus.PASS)) is False
