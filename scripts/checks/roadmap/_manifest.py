"""Entry literals for the roadmap domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_platform_roadmap",
        module="scripts.checks.roadmap.validate_platform_roadmap",
        attr="validate_platform_roadmap",
        pre=True,
        pre_globs=(
            "docs/plans/**",
            "docs/ROADMAP-*",
            "docs/DECISIONS.md",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_candidate_decision_ratification",
        module="scripts.checks.roadmap.validate_candidate_decision_ratification",
        attr="validate_candidate_decision_ratification",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_candidate_decision_supersession",
        module="scripts.checks.roadmap.validate_candidate_decision_supersession",
        attr="validate_candidate_decision_supersession",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_product_roadmap",
        module="scripts.checks.roadmap.validate_product_roadmap",
        attr="validate_product_roadmap",
        product_coupled=True,
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_plan_documents",
        module="scripts.checks.roadmap.validate_plan_documents",
        attr="validate_plan_documents",
        pre=True,
        pre_globs=(
            "docs/plans/**",
            "docs/ROADMAP-*",
            "docs/DECISIONS.md",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_fallback_reevaluation",
        module="scripts.checks.roadmap.validate_fallback_reevaluation",
        attr="validate_fallback_reevaluation",
        pre=True,
        pre_globs=(
            "docs/plans/**",
            "docs/ROADMAP-*",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_tier_floor",
        module="scripts.checks.roadmap.validate_tier_floor",
        attr="validate_tier_floor",
        pre=True,
        pre_globs=(
            "docs/plans/**",
            "docs/ROADMAP-*",
            "docs/DECISIONS.md",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="_check_graduation_guard",
        module="scripts.checks.roadmap.check_graduation_guard",
        attr="_check_graduation_guard",
        full_segment="full_after_lint",
    ),
)
