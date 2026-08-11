"""Entry literals for the iam_tf domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_environment_taxonomy",
        module="scripts.checks.iam_tf.validate_environment_taxonomy",
        attr="validate_environment_taxonomy",
        product_coupled=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_authority_budget",
        module="scripts.checks.iam_tf.validate_authority_budget",
        attr="validate_authority_budget",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_boundary_attached",
        module="scripts.checks.iam_tf.validate_boundary_attached",
        attr="validate_boundary_attached",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_invoke_implies_resolve",
        module="scripts.checks.iam_tf.validate_invoke_implies_resolve",
        attr="validate_invoke_implies_resolve",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_ci_refresh_read_coverage",
        module="scripts.checks.iam_tf.validate_ci_refresh_read_coverage",
        attr="validate_ci_refresh_read_coverage",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_iam_policy_size",
        module="scripts.checks.iam_tf.validate_iam_policy_size",
        attr="validate_iam_policy_size",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_convergence_writer_isolation",
        module="scripts.checks.iam_tf.validate_convergence_writer_isolation",
        attr="validate_convergence_writer_isolation",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_iam_runner_policy",
        module="scripts.checks.iam_tf.validate_iam_runner_policy",
        attr="validate_iam_runner_policy",
        pre=True,
        full_segment="full_after_terraform_checks",
    ),
    Entry(
        name="validate_terraform_try",
        module="scripts.checks.iam_tf.validate_terraform_try",
        attr="validate_terraform_try",
    ),
)
