"""Bundle-core assembly for scripts.ci_rca.evidence (Decision 80/104/124 decomposition).

Split out of the former scripts/ci_rca/evidence.py monolith (ci-rca-evidence-fidelity) to hold
the 500-SLOC budget: _assemble_core is the largest single self-contained unit (tier/gate
resolution + fingerprint + bundle-dict assembly), used only internally by generate_bundles.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

from scripts.ci_rca.fingerprint import compute_fingerprint_v2


def _slugify_workflow(workflow_name: str) -> str:
    """Mirror ci-rca.yml's WORKFLOW_SLUG shell derivation so the fingerprint's workflow
    component matches the same slug the workflow computes independently for status contexts."""
    slug = workflow_name.lower().replace(" ", "_").replace("/", "-")
    return re.sub(r"[^a-z0-9_-]", "", slug)


def _resolve_current_pre_runtime() -> float | None:
    """Read the maintained env stamp CI_RCA_PRE_RUNTIME_SECONDS; total, never raises."""
    raw = os.environ.get("CI_RCA_PRE_RUNTIME_SECONDS")
    if raw is None:
        return None
    try:
        val = float(raw.strip())
    except (ValueError, AttributeError):
        return None
    if not math.isfinite(val) or val <= 0:
        return None
    return val


def _assemble_core(
    workflow_run_id: int,
    workflow_name: str,
    failed_check: str,
    failure_category: str,
    classification_source: str,
    validate_path: Path | None,
    taxonomy_path: Path | None,
    vacuous_pass: "bool | str" = "undetermined",
    merge_gate_test_coverage: str = "undetermined",
    coverage_regression: "bool | str" = "undetermined",
    first_error_signature: str = "",
    error_signature: str = "",
    affected_nodeids: list[str] | None = None,
) -> dict[str, Any]:
    from scripts.ci_rca.taxonomy import load_taxonomy, resolve_workflow_tier
    from scripts.ci_rca.tier_map import (
        AST_WALKER_VERSION,
        build_tier_membership,
        compute_earliest_viable_gate,
        probe_runtime,
    )
    from scripts.ci_rca.vacuous_pass import compute_escape_mode

    taxonomy = load_taxonomy(taxonomy_path)
    taxonomy_version = taxonomy.get("taxonomy_version", 1)
    wf_tier = resolve_workflow_tier(workflow_name, taxonomy_path)
    actual_gate = wf_tier if wf_tier != "unknown" else None
    gate_is_postmerge_canary = wf_tier == "CI"

    tier_membership = build_tier_membership(validate_path)
    ast_walker_error: str | None = None
    if tier_membership is None:
        ast_walker_error = "AST parse failure -- see logs"

    runtime_confidence, median_sec = probe_runtime(failed_check, validate_path)
    pre_runtime = _resolve_current_pre_runtime()
    earliest_gate, evg_rationale = compute_earliest_viable_gate(
        failed_check, tier_membership, runtime_confidence, median_sec, current_pre_runtime=pre_runtime
    )

    escape_mode = compute_escape_mode(
        vacuous_pass=vacuous_pass,
        merge_gate_test_coverage=merge_gate_test_coverage,
        gate_is_postmerge_canary=gate_is_postmerge_canary,
        coverage_regression=coverage_regression,
    )

    check_tiers = None
    if tier_membership is not None:
        check_tiers = tier_membership.get(failed_check)

    # ci-rca-identity-lifecycle: v2 grouping fingerprint, anchored on error_signature (the
    # failure's deterministic CAUSE, junit-parsed or log-tail-derived) -- invariant to
    # run_id/timestamp/head_sha, distinct across differing error_signature/failure_category, and
    # SAME across distinct failed_checks that share the same underlying cause (cause grouping).
    # Deliberately separate from the bundle's canonical sha256 (a whole-bundle integrity hash).
    resolved_error_signature = error_signature or first_error_signature
    fingerprint = compute_fingerprint_v2(_slugify_workflow(workflow_name), failure_category, resolved_error_signature)

    bundle: dict[str, Any] = {
        "schema_version": 3,
        "workflow_run_id": workflow_run_id,
        "workflow_name": workflow_name,
        "workflow_to_tier_resolution": wf_tier,
        "failed_check": failed_check,
        "failure_category": failure_category,
        "fingerprint": fingerprint,
        "fingerprint_version": 2,
        "error_signature": resolved_error_signature,
        "affected_nodeids": affected_nodeids or [],
        "first_error_signature": first_error_signature,
        "classification_source": classification_source,
        "tier_membership": check_tiers,
        "earliest_viable_gate": earliest_gate,
        "earliest_viable_gate_rationale": evg_rationale,
        "pre_runtime_seconds": pre_runtime,
        "runtime_confidence": runtime_confidence,
        "actual_gate_that_caught_it": actual_gate,
        "gate_is_postmerge_canary": gate_is_postmerge_canary,
        "vacuous_pass": vacuous_pass,
        "merge_gate_test_coverage": merge_gate_test_coverage,
        "coverage_regression": coverage_regression,
        "escape_mode": escape_mode,
        "related_recs_by_category": [],
        "decision_records_cited": ["Decision 43", "Decision 60"],
        "ast_walker_version": AST_WALKER_VERSION,
        "taxonomy_version": taxonomy_version,
    }
    if ast_walker_error:
        bundle["ast_walker_error"] = ast_walker_error
    return bundle
