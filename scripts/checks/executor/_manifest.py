"""Entry literals for the executor domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_executor_boundary",
        module="scripts.checks.executor.validate_executor_boundary",
        attr="validate_executor_boundary",
        full_segment="full_after_lint",
    ),
)
