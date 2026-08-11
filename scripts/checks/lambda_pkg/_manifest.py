"""Entry literals for the lambda_pkg domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_lambda_manifests",
        module="scripts.checks.lambda_pkg.validate_lambda_manifests",
        attr="validate_lambda_manifests",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lambda_manifest_coverage",
        module="scripts.checks.lambda_pkg.validate_lambda_manifest_coverage",
        attr="validate_lambda_manifest_coverage",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lambda_bundle_completeness",
        module="scripts.checks.lambda_pkg.validate_lambda_bundle_completeness",
        attr="validate_lambda_bundle_completeness",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_lambda_deploy_gating",
        module="scripts.checks.lambda_pkg.validate_lambda_deploy_gating",
        attr="validate_lambda_deploy_gating",
        full_segment="full_after_lint",
    ),
)
