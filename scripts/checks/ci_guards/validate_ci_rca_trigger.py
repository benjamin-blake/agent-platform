"""ci-rca.yml trigger gate (Decision 60)."""

from __future__ import annotations

import sys

from scripts.checks import _common, registry
from scripts.checks.ci_guards._shared import _ensure_root_on_path


@registry.register("validate_ci_rca_trigger", owner="platform")
def validate_ci_rca_trigger(failed: list[str]) -> None:
    """Assert ci-rca.yml fires only on the authoritative main-branch CI gate.

    Wires the ci-rca-filter guard from scripts/verify_ci_workflow.py into the
    presubmit tier per Decision 60: a check is only a gate if it runs via validate.py.
    """
    print("\n=== ci-rca trigger gate ===")
    root_str = str(_common.ROOT)
    injected = _ensure_root_on_path()
    try:
        from scripts.verify_ci_workflow import _check_ci_rca_filter

        _check_ci_rca_filter()
        print("  PASS: ci-rca trigger gate (main-branch gate + FILED: marker contract present)")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        failed.append("ci-rca trigger gate")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
