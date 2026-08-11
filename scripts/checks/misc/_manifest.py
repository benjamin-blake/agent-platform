"""Entry literals for the misc domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_invariants",
        module="scripts.checks.misc.validate_invariants",
        attr="validate_invariants",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_test_coverage",
        module="scripts.checks.misc.validate_test_coverage",
        attr="validate_test_coverage",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_coverage_baseline_edits",
        module="scripts.checks.misc.coverage_baseline",
        attr="validate_coverage_baseline_edits",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_scheduled_agent_logs",
        module="scripts.checks.misc.validate_scheduled_agent_logs",
        attr="validate_scheduled_agent_logs",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ghas_probe",
        module="scripts.checks.misc.validate_ghas_probe",
        attr="validate_ghas_probe",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ducklake_version_lockstep",
        module="scripts.checks.misc.validate_ducklake_version_lockstep",
        attr="validate_ducklake_version_lockstep",
        pre=True,
        full_segment="full_after_lint",
    ),
)
