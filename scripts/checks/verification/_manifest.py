"""Entry literals for the verification domain's registered checks (Decision 169, amends Decision 104).

Bare string-literal module=/attr= pairs only -- see docs/contracts/check-manifest.yaml. Aggregated
by scripts/checks/registry.py; never imported by scripts/validate.py directly.
"""

from __future__ import annotations

from scripts.checks._schema import Entry

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="validate_verification_harness",
        module="scripts.checks.verification.validate_verification_harness",
        attr="validate_verification_harness",
        full_segment="full_after_ensure_fresh_dq",
    ),
    Entry(
        name="validate_handoff_full_tier",
        module="scripts.checks.verification.validate_handoff_full_tier",
        attr="validate_handoff_full_tier",
        pre=True,
        pre_globs=("docs/plans/**",),
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_hermeticity_flags",
        module="scripts.checks.verification.validate_hermeticity_flags",
        attr="validate_hermeticity_flags",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_verifier_hermeticity",
        module="scripts.checks.verification.validate_verifier_hermeticity",
        attr="validate_verifier_hermeticity",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_verifier_same_pr_guard",
        module="scripts.checks.verification.validate_verifier_same_pr_guard",
        attr="validate_verifier_same_pr_guard",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_verification_registry",
        module="scripts.checks.verification.validate_verification_registry",
        attr="validate_verification_registry",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_graduation_completeness",
        module="scripts.checks.verification.validate_graduation_completeness",
        attr="validate_graduation_completeness",
        pre=True,
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_differential_gate_baseline",
        module="scripts.checks.verification.validate_differential_gate_baseline",
        attr="validate_differential_gate_baseline",
        full_segment="full_after_lint",
    ),
    Entry(
        name="validate_vp_replay",
        module="scripts.checks.verification.validate_vp_replay",
        attr="validate_vp_replay",
        pre=True,
    ),
)
