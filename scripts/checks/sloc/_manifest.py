"""Entry literals for the sloc domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_cc_limits",
        module="scripts.checks.sloc.cc_limits",
        attr="validate_cc_limits",
        pre=True,
        pre_globs=("**/*.py",),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_sloc_limits",
        module="scripts.checks.sloc.sloc_limits",
        attr="validate_sloc_limits",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_complexity",
        module="scripts.checks.sloc.complexity",
        attr="validate_complexity",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_sloc_budget_raises",
        module="scripts.checks.sloc.validate_sloc_budget_raises",
        attr="validate_sloc_budget_raises",
        pre=True,
    ),
)
