"""Plan scope registration-closure check (plan-obligation-closure).

Thin @register(...) delegate over scripts.roadmap.plan_obligations -- that module owns the
registration-closure engine and reads its obligation map from docs/contracts/plan-obligations.yaml
at check time. Runs in --pre (gated on docs/plans/** changes) and the full tier's
full_after_lint segment (scripts/checks/roadmap/_manifest.py).
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks import registry
from scripts.roadmap import plan_obligations


@registry.register("validate_plan_scope_closure", owner="platform")
def validate_plan_scope_closure(failed: list[str], plan_paths: list[Path] | None = None) -> None:
    """Flag a net-new, schema_version >= 4 IMPLEMENTATION plan whose scope omits a
    mechanically-derivable companion registration (docs/contracts/plan-obligations.yaml).

    `plan_paths` overrides plan discovery and is accepted UNFILTERED -- absolute or relative,
    with no re-application of the net-new/schema-version/PLAN_PATH_RE diff-derivation gate -- so
    fixture-driven callers (this check's own VP steps, its mirror tests) can target synthetic
    plans that never appear in a real git diff. `None` (real dispatch) derives the net-new v4
    IMPLEMENTATION set from the git diff via plan_obligations.net_new_v4_implementation_plan_paths
    -- this check never globs docs/plans/.
    """
    print("\n=== Plan scope registration-closure validation ===")
    paths = plan_obligations.net_new_v4_implementation_plan_paths() if plan_paths is None else plan_paths
    if not paths:
        print("  PASS: no net-new IMPLEMENTATION plan (schema_version >= 4) to check.")
        return
    errors: list[str] = []
    for path in paths:
        errors.extend(plan_obligations.evaluate_plan(path))
    for error in errors:
        print(f"  FAIL: {error}")
    if errors:
        # Each finding is appended individually (not a single summary label) -- the CI-RCA
        # taxonomy row and this check's own callers key off the per-omission path detail, not a
        # fixed "Plan scope registration-closure validation" string.
        failed.extend(errors)
    else:
        print(f"  PASS: {len(paths)} plan(s) closure-complete.")
