"""Entry literals for the deps domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_requirements",
        module="scripts.checks.deps.validate_requirements",
        attr="validate_requirements",
        full_segment="full_after_dependency_health",
    ),
    Entry(
        name="validate_import_contracts",
        module="scripts.checks.deps.validate_import_contracts",
        attr="validate_import_contracts",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lockfile_sync",
        module="scripts.checks.deps.validate_lockfile_sync",
        attr="validate_lockfile_sync",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_dependency_graph_freshness",
        module="scripts.checks.deps.validate_dependency_graph_freshness",
        attr="validate_dependency_graph_freshness",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_check_manifests",
        module="scripts.checks.deps.validate_check_manifests",
        attr="validate_check_manifests",
        pre=True,
        full_segment="full_after_lint",
    ),
)
