"""Entry literals for the typing domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_mypy_baseline_edits",
        module="scripts.checks.typing.mypy_baseline",
        attr="validate_mypy_baseline_edits",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_mypy_ratchet",
        module="scripts.checks.typing.mypy_baseline",
        attr="validate_mypy_ratchet",
        full_segment="full_after_unit_tests",
    ),
)
