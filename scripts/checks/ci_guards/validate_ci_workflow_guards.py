"""CI workflow structural invariants gate (Decision 60, CD.21)."""

from __future__ import annotations

import sys
from collections.abc import Callable

from scripts.checks import _common, registry
from scripts.checks.ci_guards._shared import _ensure_root_on_path


def _load_guards() -> list[tuple[str, Callable[[], None]]]:
    """Import the guard functions from scripts/verify_ci_workflow.py and pair each with its
    presubmit label. Called both at module load (to populate the module-level _GUARDS constant
    below) and again on every validate_ci_workflow_guards() call, so an import-time failure of
    scripts.verify_ci_workflow at CALL time is still caught by that function's own try/except
    (rec-2027) rather than only crashing at first import.
    """
    from scripts.verify_ci_workflow import (
        _check_apply_rca_fallback,
        _check_canary,
        _check_ci_rca_fetch_classification,
        _check_concurrency,
        _check_fetch_depth,
        _check_jobs_and_flags,
        _check_recovery_workflow_topology,
        _check_signal_green_needs,
        _check_terraform_apply_concurrency,
        _check_validate_single_source,
    )

    return [
        ("jobs-and-flags", _check_jobs_and_flags),
        ("fetch-depth", _check_fetch_depth),
        ("concurrency", _check_concurrency),
        ("canary", _check_canary),
        ("apply-rca-fallback", _check_apply_rca_fallback),
        ("validate-single-source", _check_validate_single_source),
        ("signal-green-needs", _check_signal_green_needs),
        ("terraform-apply-concurrency", _check_terraform_apply_concurrency),
        ("ci-rca-fetch-classification", _check_ci_rca_fetch_classification),
        ("recovery-workflow-topology", _check_recovery_workflow_topology),
    ]


# Module-level so VP steps can assert real tuple membership (rather than a source-text proxy
# that a mere import-line-plus-docstring-mention would satisfy without the guard ever running) --
# populated by a real import, without requiring a validate_ci_workflow_guards() call first. No
# sys.path injection needed here (unlike the defensive call-time import below): this module's
# own dotted import path already proves the `scripts` package root is resolvable, and
# scripts.verify_ci_workflow is a sibling submodule reachable the same way. Wrapped in try/except
# (never raise during import, AGENTS.md Safety) -- scripts/validate.py imports this module
# unconditionally, so an import-time failure of scripts.verify_ci_workflow must degrade _GUARDS
# to empty rather than crashing the whole validate run; validate_ci_workflow_guards()'s own
# call-time try/except (rec-2027) still reports the failure as a single gate failure.
try:
    _GUARDS: list[tuple[str, Callable[[], None]]] = _load_guards()
except Exception:
    _GUARDS = []


@registry.register("validate_ci_workflow_guards", owner="platform")
def validate_ci_workflow_guards(failed: list[str]) -> None:
    """Assert CI workflow structural invariants are met (Decision 60, CD.21).

    Wires _check_jobs_and_flags, _check_fetch_depth, _check_concurrency, _check_canary,
    _check_apply_rca_fallback, _check_validate_single_source, _check_signal_green_needs,
    _check_terraform_apply_concurrency, _check_ci_rca_fetch_classification, and
    _check_recovery_workflow_topology from scripts/verify_ci_workflow.py into the presubmit tier.
    Each guard failure appends a distinct label; a non-AssertionError exception
    records a failure rather than crashing presubmit (rec-2027 pattern).
    """
    print("\n=== ci-workflow guards gate ===")
    root_str = str(_common.ROOT)
    injected = _ensure_root_on_path()
    try:
        guards = _load_guards()
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
