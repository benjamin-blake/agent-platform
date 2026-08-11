"""Entry literals for the contracts domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_prompt_compliance",
        module="scripts.checks.contracts.validate_prompt_compliance",
        attr="validate_prompt_compliance",
        full_segment="full_after_dependency_health",
    ),
    Entry(
        name="validate_instruction_architecture_layers",
        module="scripts.checks.contracts.validate_instruction_architecture_layers",
        attr="validate_instruction_architecture_layers",
        full_segment="full_after_dependency_health",
    ),
    Entry(
        name="validate_no_underscore_instructions",
        module="scripts.checks.contracts.validate_no_underscore_instructions",
        attr="validate_no_underscore_instructions",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_claude_md_pointer_invariant",
        module="scripts.checks.contracts.validate_claude_md_pointer_invariant",
        attr="validate_claude_md_pointer_invariant",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_intent_doc_freeze",
        module="scripts.checks.contracts.validate_intent_doc_freeze",
        attr="validate_intent_doc_freeze",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_contract_drift",
        module="scripts.checks.contracts.validate_contract_drift",
        attr="validate_contract_drift",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_data_model_standard",
        module="scripts.checks.contracts.validate_data_model_standard",
        attr="validate_data_model_standard",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_portal_drift",
        module="scripts.checks.contracts.validate_portal_drift",
        attr="validate_portal_drift",
        full_segment="full_after_lint",
    ),
)
