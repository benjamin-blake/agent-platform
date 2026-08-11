"""Entry literals for the ci_guards domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_workflow_agent_safety",
        module="scripts.checks.ci_guards.validate_workflow_agent_safety",
        attr="validate_workflow_agent_safety",
        pre=True,
        full_segment="full_after_dependency_health",
    ),
    Entry(
        name="validate_ci_rca_trigger",
        module="scripts.checks.ci_guards.validate_ci_rca_trigger",
        attr="validate_ci_rca_trigger",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ci_workflow_guards",
        module="scripts.checks.ci_guards.validate_ci_workflow_guards",
        attr="validate_ci_workflow_guards",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_actions_evidence",
        module="scripts.checks.ci_guards.validate_actions_evidence",
        attr="validate_actions_evidence",
        pre=True,
        pre_globs=(
            ".github/workflows/**",
            ".github/actions/**",
            "docs/contracts/github-actions-evidence.yaml",
            "scripts/checks/ci_guards/validate_actions_evidence.py",
        ),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_pr_conflict_signal",
        module="scripts.checks.ci_guards.validate_pr_conflict_signal",
        attr="validate_pr_conflict_signal",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_masked_errexit_steps",
        module="scripts.checks.ci_guards.validate_masked_errexit_steps",
        attr="validate_masked_errexit_steps",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_composite_action_manifests",
        module="scripts.checks.ci_guards.validate_composite_action_manifests",
        attr="validate_composite_action_manifests",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_composite_action_shell_bodies",
        module="scripts.checks.ci_guards.validate_composite_action_shell_bodies",
        attr="validate_composite_action_shell_bodies",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_claude_p_retry_wrapper",
        module="scripts.checks.ci_guards.validate_claude_p_retry_wrapper",
        attr="validate_claude_p_retry_wrapper",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ci_rca_taxonomy",
        module="scripts.checks.ci_guards.validate_ci_rca_taxonomy",
        attr="validate_ci_rca_taxonomy",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ops_portal_patch_targets",
        module="scripts.checks.ci_guards.validate_ops_portal_patch_targets",
        attr="validate_ops_portal_patch_targets",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ci_rca_adjudication",
        module="scripts.checks.ci_guards.validate_ci_rca_adjudication",
        attr="validate_ci_rca_adjudication",
        pre=True,
        full_segment="full_after_lint",
    ),
)
