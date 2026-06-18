"""Verification harness for programmatic system checks.

Defines the base Verifier class and VerifierResult schema.
Used to implement deterministic hard gates for autonomous execution.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class VerifierStatus(Enum):
    """Canonical verification outcomes."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"

    def __str__(self) -> str:
        return self.value


class VerifierSeverity(Enum):
    """How failures affect the overall process."""

    ADVISORY = 10
    WARN = 15
    HARD_GATE = 20

    def __str__(self) -> str:
        return self.name

    @property
    def rank(self) -> int:
        """Numeric rank for comparison."""
        return self.value


class VerifierTier(Enum):
    """Verification granularity/environment."""

    V1 = "V1"
    V2 = "V2"
    V3 = "V3"

    def __str__(self) -> str:
        return self.value


class Hermeticity(Enum):
    """Clock/network/randomness disposition of a verifier.

    HERMETIC - result depends only on inputs (code structure, config, filesystem contents).
        No absolute clock reads, live network calls, or randomness. Safe to cache and replay.
    NON_HERMETIC_BY_CONSTRUCTION - result depends on wall-clock time, live filesystem state,
        network I/O, or randomness. Correct by design; the explicit declaration silences the
        validate_verifier_hermeticity AST gate in validate.py.
    """

    HERMETIC = "HERMETIC"
    NON_HERMETIC_BY_CONSTRUCTION = "NON_HERMETIC_BY_CONSTRUCTION"

    def __str__(self) -> str:
        return self.value


@dataclass
class VerifierResult:
    """The result of a single verification check."""

    name: str
    status: VerifierStatus
    message: str = ""
    duration_ms: float = 0.0
    severity: VerifierSeverity = VerifierSeverity.HARD_GATE
    covers: list[str] = field(default_factory=lambda: ["**"])

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": str(self.status),
            "message": self.message,
            "duration_ms": self.duration_ms,
            "severity": str(self.severity),
        }

    def __str__(self) -> str:
        return f"[{self.status}] ({self.severity}) {self.name}: {self.message} ({self.duration_ms:.1f}ms)"


def scope_intersects_covers(scope_files: list[str], covers: list[str]) -> bool:
    """Return True iff any glob in covers matches any path in scope_files."""
    return any(fnmatch.fnmatch(path, glob) for glob in covers for path in scope_files)


class Verifier(ABC):
    """Abstract base class for all verifiers."""

    covers: list[str] = ["**"]
    hermeticity: Hermeticity = Hermeticity.HERMETIC

    @property
    def name(self) -> str:
        """The display name of the verifier."""
        return self.__class__.__name__

    @property
    def severity(self) -> VerifierSeverity:
        """Default severity for this verifier class."""
        return VerifierSeverity.HARD_GATE

    @property
    def tier(self) -> VerifierTier:
        """Default tier for this verifier class."""
        return VerifierTier.V1

    @abstractmethod
    async def verify(self) -> VerifierResult:
        """Execute the verification check and return a result.

        Must not raise exceptions; all failures should be returned as FAIL or SKIPPED.
        """
        pass

    async def run(self) -> VerifierResult:
        """Run the verifier with timing instrumentation."""
        start_time = time.perf_counter()
        try:
            result = await self.verify()
            # Ensure severity is propagated from the class if not explicitly set in result
            if result.severity == VerifierSeverity.HARD_GATE and self.severity == VerifierSeverity.ADVISORY:
                result.severity = VerifierSeverity.ADVISORY
        except Exception as exc:  # noqa: BLE001
            result = VerifierResult(
                name=self.name,
                status=VerifierStatus.FAIL,
                message=f"Verifier raised unexpected exception: {type(exc).__name__}: {exc}",
                severity=self.severity,
            )

        result.covers = list(self.covers)
        result.duration_ms = (time.perf_counter() - start_time) * 1000
        return result


async def main() -> None:
    """CLI entry point for running verifiers."""
    parser = argparse.ArgumentParser(description="Run programmatic verifiers.")
    parser.add_argument("--tier", choices=[t.value for t in VerifierTier], help="Filter by tier")
    parser.add_argument(
        "--severity",
        choices=[s.name.lower() for s in VerifierSeverity],
        help="Minimum severity (advisory or hard_gate)",
    )
    parser.add_argument("--verifier", help="Run only the specified verifier by name (e.g. OutboxHealthVerifier)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    # Late import to avoid circular dependency during module load
    from scripts.verifiers import run_all_verifiers

    tier = VerifierTier(args.tier) if args.tier else None
    severity = VerifierSeverity[args.severity.upper()] if args.severity else None

    results = await run_all_verifiers(tier_filter=tier, min_severity=severity, verifier_name=args.verifier)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        for result in results:
            print(result)

    # Check for any HARD_GATE failures
    hard_gate_failures = [r for r in results if r.status == VerifierStatus.FAIL and r.severity == VerifierSeverity.HARD_GATE]

    if hard_gate_failures:
        if not args.json:
            print(f"\nFAILED: {len(hard_gate_failures)} hard gate(s) failed.", file=sys.stderr)
        sys.exit(1)

    if not args.json:
        print("\nPASSED: All verifiers passed or only advisory failures occurred.")


if __name__ == "__main__":
    asyncio.run(main())
