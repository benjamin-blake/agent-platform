"""Entry literals for the structural domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_structural_size_limits",
        module="scripts.checks.structural.size_limits",
        attr="validate_structural_size_limits",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_structural_size_budget_raises",
        module="scripts.checks.structural.budget_raises",
        attr="validate_structural_size_budget_raises",
        pre=True,
        full_segment="full_after_lint",
    ),
)
