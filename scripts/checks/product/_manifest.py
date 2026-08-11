"""Entry literals for the product domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_broker_env_reads",
        module="scripts.checks.product.trading.validate_broker_env_reads",
        attr="validate_broker_env_reads",
        owner="trading",
        full_segment="full_after_lint",
    ),
)
