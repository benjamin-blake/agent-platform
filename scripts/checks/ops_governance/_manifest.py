"""Entry literals for the ops_governance domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_recommendations_schema",
        module="scripts.checks.ops_governance.validate_recommendations_schema",
        attr="validate_recommendations_schema",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_outbox_staleness",
        module="scripts.checks.ops_governance.validate_outbox_staleness",
        attr="validate_outbox_staleness",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_rec_write_paths",
        module="scripts.checks.ops_governance.validate_rec_write_paths",
        attr="validate_rec_write_paths",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_decisions_local_writes",
        module="scripts.checks.ops_governance.validate_decisions_local_writes",
        attr="validate_decisions_local_writes",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_warehouse_write_sources",
        module="scripts.checks.ops_governance.validate_warehouse_write_sources",
        attr="validate_warehouse_write_sources",
        full_segment="full_after_lint",
    ),
    Entry(
        name="check_source_registry",
        module="scripts.checks.ops_governance.check_source_registry",
        attr="check_source_registry",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_pydantic_yaml_drift",
        module="scripts.checks.ops_governance.validate_pydantic_yaml_drift",
        attr="validate_pydantic_yaml_drift",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_dq_manifest_gate",
        module="scripts.checks.ops_governance.validate_dq_manifest_gate",
        attr="validate_dq_manifest_gate",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_rec_relevance_contract",
        module="scripts.checks.ops_governance.validate_rec_relevance_contract",
        attr="validate_rec_relevance_contract",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_field_semantics_drift",
        module="scripts.checks.ops_governance.validate_field_semantics_drift",
        attr="validate_field_semantics_drift",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_reconcile_pending_gate",
        module="scripts.checks.ops_governance.validate_reconcile_pending_gate",
        attr="validate_reconcile_pending_gate",
        pre=True,
        pre_globs=(
            "docs/contracts/ops_*.yaml",
            "config/lambda/ducklake/field_semantics.static.yaml",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_deploy_channel_conformance",
        module="scripts.checks.ops_governance.validate_deploy_channel_conformance",
        attr="validate_deploy_channel_conformance",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_reversal_stanzas",
        module="scripts.checks.ops_governance.validate_reversal_stanzas",
        attr="validate_reversal_stanzas",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_acceptance_literals",
        module="scripts.checks.ops_governance.validate_acceptance_literals",
        attr="validate_acceptance_literals",
        pre=True,
        pre_globs=("scripts/**",),
        full_segment="full_after_lint",
    ),
)
