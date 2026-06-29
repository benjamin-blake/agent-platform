"""Typed verification checks kernel -- closed six-slot vocabulary (CD.29).

Defines deterministic primitives for the graduated-validation model.
Adding a new primitive slot requires a new CD (CD.29 discipline).
This module must not touch the filesystem or raise at import time.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    status: CheckStatus
    message: str = ""
    actual: str = ""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

@dataclass
class BaseCheck:
    """Abstract base for all verification checks."""

    name: str
    slot: str = field(init=False)

    def run(self) -> CheckResult:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Slot 1: command_exit_zero
# ---------------------------------------------------------------------------

@dataclass
class CommandExitZeroCheck(BaseCheck):
    """Assert that a shell command exits with status 0."""

    slot: str = field(default="command_exit_zero", init=False)
    command: list[str] = field(default_factory=list)
    cwd: str | None = None

    def run(self) -> CheckResult:
        result = subprocess.run(
            self.command,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return CheckResult(status=CheckStatus.PASS, actual=str(result.returncode))
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"Command exited {result.returncode}",
            actual=result.stderr.strip() or result.stdout.strip(),
        )


# ---------------------------------------------------------------------------
# Slot 2: command_output_matches
# ---------------------------------------------------------------------------

@dataclass
class CommandOutputMatchesCheck(BaseCheck):
    """Assert that a shell command's stdout matches an expected value or regex."""

    slot: str = field(default="command_output_matches", init=False)
    command: list[str] = field(default_factory=list)
    expected: str = ""
    use_regex: bool = False
    cwd: str | None = None

    def run(self) -> CheckResult:
        result = subprocess.run(
            self.command,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        actual = result.stdout.strip()
        if self.use_regex:
            matched = bool(re.search(self.expected, actual))
        else:
            matched = actual == self.expected
        if matched:
            return CheckResult(status=CheckStatus.PASS, actual=actual)
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"Expected {'pattern' if self.use_regex else 'exact'} {self.expected!r}",
            actual=actual,
        )


# ---------------------------------------------------------------------------
# Slot 3: file_presence (file_exists + file_absent share one slot)
# ---------------------------------------------------------------------------

@dataclass
class FileExistsCheck(BaseCheck):
    """Assert that a file path exists on disk."""

    slot: str = field(default="file_presence", init=False)
    path: str = ""

    def run(self) -> CheckResult:
        from pathlib import Path  # noqa: PLC0415

        exists = Path(self.path).exists()
        if exists:
            return CheckResult(status=CheckStatus.PASS, actual="exists")
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"File not found: {self.path}",
            actual="absent",
        )


@dataclass
class FileAbsentCheck(BaseCheck):
    """Assert that a file path does NOT exist on disk."""

    slot: str = field(default="file_presence", init=False)
    path: str = ""

    def run(self) -> CheckResult:
        from pathlib import Path  # noqa: PLC0415

        exists = Path(self.path).exists()
        if not exists:
            return CheckResult(status=CheckStatus.PASS, actual="absent")
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"File should not exist: {self.path}",
            actual="exists",
        )


# ---------------------------------------------------------------------------
# Slot 4: grep_count
# ---------------------------------------------------------------------------

@dataclass
class GrepCountCheck(BaseCheck):
    """Assert that the count of grep matches in a file meets a comparison."""

    slot: str = field(default="grep_count", init=False)
    path: str = ""
    pattern: str = ""
    # Operator: "eq", "gt", "gte", "lt", "lte"
    operator: str = "eq"
    count: int = 0

    def run(self) -> CheckResult:
        from pathlib import Path  # noqa: PLC0415

        try:
            text = Path(self.path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return CheckResult(
                status=CheckStatus.FAIL,
                message=f"File not found: {self.path}",
            )

        matches = len(re.findall(self.pattern, text))
        op = self.operator
        expected = self.count
        passed = (
            (op == "eq" and matches == expected)
            or (op == "gt" and matches > expected)
            or (op == "gte" and matches >= expected)
            or (op == "lt" and matches < expected)
            or (op == "lte" and matches <= expected)
        )
        if passed:
            return CheckResult(status=CheckStatus.PASS, actual=str(matches))
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"grep_count {op} {expected}: got {matches}",
            actual=str(matches),
        )


# ---------------------------------------------------------------------------
# Slot 5: test_selector
# ---------------------------------------------------------------------------

@dataclass
class TestSelectorCheck(BaseCheck):
    """Assert that a specific pytest node passes."""

    slot: str = field(default="test_selector", init=False)
    # e.g. "tests/test_foo.py::MyClass::test_bar"
    node_id: str = ""
    cwd: str | None = None

    def run(self) -> CheckResult:
        import sys  # noqa: PLC0415

        result = subprocess.run(
            [sys.executable, "-m", "pytest", self.node_id, "-v", "--tb=short"],
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return CheckResult(status=CheckStatus.PASS, actual=self.node_id)
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"pytest node failed: {self.node_id}",
            actual=result.stdout[-500:] if result.stdout else result.stderr[-500:],
        )


# ---------------------------------------------------------------------------
# Slot 6: metric_under_threshold
# ---------------------------------------------------------------------------

@dataclass
class MetricUnderThresholdCheck(BaseCheck):
    """Assert that a numeric metric from a command stays below a threshold."""

    slot: str = field(default="metric_under_threshold", init=False)
    command: list[str] = field(default_factory=list)
    threshold: float = 0.0
    cwd: str | None = None

    def run(self) -> CheckResult:
        result = subprocess.run(
            self.command,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        raw = result.stdout.strip()
        try:
            value = float(raw)
        except ValueError:
            return CheckResult(
                status=CheckStatus.FAIL,
                message=f"Could not parse numeric metric from output: {raw!r}",
                actual=raw,
            )
        if value < self.threshold:
            return CheckResult(status=CheckStatus.PASS, actual=str(value))
        return CheckResult(
            status=CheckStatus.FAIL,
            message=f"Metric {value} >= threshold {self.threshold}",
            actual=str(value),
        )


# ---------------------------------------------------------------------------
# Closed-vocabulary registry (CD.29 discipline)
# ---------------------------------------------------------------------------

# All concrete check classes.  FileExistsCheck and FileAbsentCheck share the
# slot "file_presence" so CANONICAL_SLOTS has 6 entries, not 7.
ALL_CHECK_TYPES: tuple[type[BaseCheck], ...] = (
    CommandExitZeroCheck,
    CommandOutputMatchesCheck,
    FileExistsCheck,
    FileAbsentCheck,
    GrepCountCheck,
    TestSelectorCheck,
    MetricUnderThresholdCheck,
)

# The six canonical slots.  Size is INVARIANT -- extend only via a new CD.
CANONICAL_SLOTS: frozenset[str] = frozenset(cls.__dataclass_fields__["slot"].default for cls in ALL_CHECK_TYPES)  # type: ignore[attr-defined]

SLOT_COUNT: int = len(CANONICAL_SLOTS)  # must equal 6


def _assert_slot_count() -> None:
    """Guard invariant: exactly 6 slots.  Raises ValueError if violated."""
    if SLOT_COUNT != 6:
        raise ValueError(f"CD.29 violation: expected 6 canonical slots, found {SLOT_COUNT}: {sorted(CANONICAL_SLOTS)}")


_assert_slot_count()


# ---------------------------------------------------------------------------
# Differential admission gate
# ---------------------------------------------------------------------------

def is_admitted(check: BaseCheck, revert_runner: "Callable[[BaseCheck], CheckResult]") -> bool:
    """Return True iff the check FAILS when the guarded change is reverted.

    A check that passes both before and after the change is tautological and
    must be rejected.  A check that fails on the reverted (pre-change) tree is
    a genuine gate.

    Args:
        check: The candidate verification check.
        revert_runner: A callable that executes ``check`` in the pre-change
            environment (e.g. a subprocess that checks out origin/main and
            returns the result).  The harness supplies this; production wiring
            is validate.py (CI) or the Step-Functions executor verify-state
            (deferred per CD.27).
    """
    result = revert_runner(check)
    return result.status == CheckStatus.FAIL


# make Callable available for the type annotation above without a runtime import
from collections.abc import Callable  # noqa: E402
