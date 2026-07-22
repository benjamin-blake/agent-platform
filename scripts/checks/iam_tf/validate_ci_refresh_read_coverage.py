"""CI refresh-read + write coverage gate (facade -- Decision 128 decomposition, Decision 144 / T2.48).

This module is a thin facade/orchestrator over two cohesive submodules (each < 500 SLOC, Decision 128
decompose-by-default, not raise):
  - _read_coverage: the READ classification maps + shared HCL parse/scan/match primitives + the
    per-resource read-coverage assertion (extracted byte-equivalent from the pre-decomposition module).
  - _write_coverage: the WRITE-coverage map (managed resource type -> required write verbs + prefix)
    + the assertion that github_ci_apply's inline policy write-covers every apply-role-written type
    (c5, DEP-01; closes the read-covered-but-write-missing recurrence rec-2703/rec-2757).

The registered check name (validate_ci_refresh_read_coverage) and its registry entry are UNCHANGED.
The private parse/resolve helpers are re-exported here so their existing branch-level tests (which
import them from this module path) keep passing unmodified.
"""

from __future__ import annotations

from scripts.checks import _common, registry
from scripts.checks.iam_tf._read_coverage import (
    _BOOTSTRAP_TF_REL,
    _PERSONAL_DIR_REL,
    ROLE_APPLY,
    _action_matches,  # noqa: F401 -- re-exported for tests
    _check_resource,
    _extract_bracket_block,  # noqa: F401 -- re-exported for tests
    _extract_capitalized_field,  # noqa: F401 -- re-exported for tests
    _literal_or_prefix_match,  # noqa: F401 -- re-exported for tests
    _parse_bootstrap_statements,
    _resolve_resource_name,  # noqa: F401 -- re-exported for tests
    _resolve_role_statements,
    _resolve_value,  # noqa: F401 -- re-exported for tests
    _resource_covered,  # noqa: F401 -- re-exported for tests
    _scan_resources,
    _split_top_level_objects,  # noqa: F401 -- re-exported for tests
)
from scripts.checks.iam_tf._write_coverage import check_write_coverage


@registry.register("validate_ci_refresh_read_coverage", owner="platform")
def validate_ci_refresh_read_coverage(failed: list[str]) -> None:
    """Whole-module refresh-read + write coverage gate (rec-2702 anti-recurrence + Decision 144 c5).

    READ half (unchanged): every grant-requiring resource across terraform/personal/*.tf must be
    refresh-read-covered in ALL THREE plan-capable role policies -- github_ci_apply
    (terraform/bootstrap/github_ci_apply.tf), github_ci_plan + github_ci_drift
    (terraform/personal/oidc.tf). A resource of a type this module does not classify FAILS LOUD.

    WRITE half (Decision 144 / T2.48 c5, DEP-01): github_ci_apply's inline policy must WRITE-cover
    every apply-role-written managed type (aws_lambda_function / aws_cloudwatch_log_group /
    aws_cloudwatch_metric_alarm / aws_cloudwatch_event_rule / aws_iam_role). A write-managed type
    with no covering write grant FAILS LOUD -- the read-covered-but-write-missing recurrence
    (rec-2703/rec-2757) the enumerated model kept reproducing.

    Credential-free (pure text parsing, no boto3/terraform invocation) -- eligible for --pre and
    full tiers. Test isolation: patch `scripts.checks._common.ROOT` (both paths are computed from
    it at call time), mirroring validate_invoke_implies_resolve's convention.
    """
    print("\n=== CI refresh-read + write coverage gate (rec-2702 + Decision 144 c5) ===")
    key = "ci-refresh-read-coverage:"

    personal_dir = _common.ROOT / _PERSONAL_DIR_REL
    bootstrap_tf = _common.ROOT / _BOOTSTRAP_TF_REL
    oidc_tf = personal_dir / "oidc.tf"

    try:
        bootstrap_text = bootstrap_tf.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"{key} cannot read {bootstrap_tf}: {exc}")
        print(f"  FAIL: cannot read bootstrap HCL: {exc}")
        return
    try:
        oidc_text = oidc_tf.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"{key} cannot read {oidc_tf}: {exc}")
        print(f"  FAIL: cannot read oidc.tf: {exc}")
        return

    apply_statements = _parse_bootstrap_statements(bootstrap_text, "github_ci_apply")
    if not apply_statements:
        failed.append(f"{key} no statements parsed from the github_ci_apply policy in {bootstrap_tf.name}")
        print("  FAIL: could not parse the apply role's inline policy statements -- has the HCL shape changed?")
        return

    plan_drift_statements = _resolve_role_statements(oidc_text)
    if plan_drift_statements is None:
        failed.append(f"{key} could not resolve github_ci_plan/github_ci_drift role policies in {oidc_tf.name}")
        print("  FAIL: could not resolve the plan/drift role policy documents -- has the HCL shape changed?")
        return

    role_statements: dict[str, list[dict]] = {ROLE_APPLY: apply_statements, **plan_drift_statements}

    resources, locals_map, attr_index = _scan_resources(personal_dir)
    if not resources:
        failed.append(f"{key} no terraform resources discovered under {personal_dir}")
        print("  FAIL: no terraform resources discovered -- has the module moved?")
        return

    checked = 0
    for rtype, rname, fname in resources:
        findings, was_checked = _check_resource(rtype, rname, fname, locals_map, attr_index, role_statements, key)
        failed.extend(findings)
        if was_checked:
            checked += 1

    write_types = check_write_coverage(apply_statements, resources, failed, key)

    if not any(f.startswith(key) for f in failed):
        print(
            f"  PASS: all {checked} grant-requiring resources are refresh-read-covered in apply/plan/drift, "
            f"and github_ci_apply write-covers all {write_types} apply-role-written managed types."
        )


if __name__ == "__main__":  # pragma: no cover
    # Standalone entry point so `python -m scripts.checks.iam_tf.validate_ci_refresh_read_coverage`
    # actually exercises the check (exit 1 on any finding), mirroring validate_ghas_probe's runner.
    _failed: list[str] = []
    validate_ci_refresh_read_coverage(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
