"""Entry literals for the prose domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_prose_limits",
        module="scripts.checks.prose.prose_limits",
        attr="validate_prose_limits",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_prose_budget_raises",
        module="scripts.checks.prose.prose_budget_raises",
        attr="validate_prose_budget_raises",
        pre=True,
    ),
)
