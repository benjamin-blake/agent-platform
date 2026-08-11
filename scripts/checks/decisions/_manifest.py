"""Entry literals for the decisions domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_decisions_size",
        module="scripts.checks.decisions.validate_decisions_size",
        attr="validate_decisions_size",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_decisions_index_freshness",
        module="scripts.checks.decisions.validate_decisions_index_freshness",
        attr="validate_decisions_index_freshness",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_decision_entry_conformance",
        module="scripts.checks.decisions.validate_decision_entry_conformance",
        attr="validate_decision_entry_conformance",
        pre=True,
        pre_globs=(
            "docs/DECISIONS.md",
            "docs/DECISIONS_ARCHIVE.md",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_supersession_annotations",
        module="scripts.checks.decisions.validate_supersession_annotations",
        attr="validate_supersession_annotations",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_decision_currency",
        module="scripts.checks.decisions.validate_decision_currency",
        attr="validate_decision_currency",
        pre=True,
        pre_globs=(
            "docs/DECISIONS.md",
            "docs/DECISIONS_ARCHIVE.md",
            "docs/decisions-index.json",
            "docs/contracts/decision-entry.yaml",
            ".claude/skills/decision-scout/SKILL.md",
            "scripts/checks/decisions/validate_decision_currency.py",
        ),
        full_segment="full_after_lint",
    ),
)
