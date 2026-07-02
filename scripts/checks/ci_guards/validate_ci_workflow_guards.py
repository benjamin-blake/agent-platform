"""CI workflow structural invariants gate (Decision 60, CD.21)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry
from scripts.checks.ci_guards._shared import _ensure_root_on_path


@registry.register("validate_ci_workflow_guards", owner="platform")
def validate_ci_workflow_guards(failed: list[str]) -> None:
    """Assert CI workflow structural invariants are met (Decision 60, CD.21).

    Wires _check_jobs_and_flags, _check_fetch_depth, _check_concurrency,
    _check_canary, and _check_apply_rca_fallback from scripts/verify_ci_workflow.py
    into the presubmit tier.
    Each guard failure appends a distinct label; a non-AssertionError exception
    records a failure rather than crashing presubmit (rec-2027 pattern).
    """
    print("\n=== ci-workflow guards gate ===")
    root_str = str(_common.ROOT)
    injected = _ensure_root_on_path()
    try:
        from scripts.verify_ci_workflow import (
            _check_apply_rca_fallback,
            _check_canary,
            _check_concurrency,
            _check_fetch_depth,
            _check_jobs_and_flags,
            _check_signal_green_needs,
            _check_validate_single_source,
        )

        guards = [
            ("jobs-and-flags", _check_jobs_and_flags),
            ("fetch-depth", _check_fetch_depth),
            ("concurrency", _check_concurrency),
            ("canary", _check_canary),
            ("apply-rca-fallback", _check_apply_rca_fallback),
            ("validate-single-source", _check_validate_single_source),
            ("signal-green-needs", _check_signal_green_needs),
        ]
        for label, fn in guards:
            try:
                fn()
                print(f"  PASS: {label}")
            except Exception as exc:
                print(f"  FAIL: {label}: {exc}")
                failed.append(f"ci-workflow guard: {label}")
    except Exception as exc:
        # Import or setup failure (e.g. verify_ci_workflow unimportable) must
        # record a gate failure, not crash presubmit (rec-2027).
        print(f"  FAIL: ci-workflow guards gate (import/setup): {exc}")
        failed.append("ci-workflow guards gate")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
