# complexity-waiver: decision-43
#!/usr/bin/env python3
"""Local CI validation script. Run before every commit.

Runs validation checks that mirror the GitHub Actions CI pipeline.
Default (no flags) runs the full check suite. Use --pre for fast lint/format
checks only during implementation.

Thin CLI (Decision 104): every check lives in scripts/checks/<domain>/ and is
tagged in the scripts/checks/registry.py check registry. This file retains
only the argparse surface, the recursion/branch guards, the fast-tier budget
assertion, the non-check scaffolding steps (lint, precommit, mypy, explicit
pytest, unit-test invoke_step, dependency/terraform gates), and facade
re-exports of every extracted check/helper so both `patch("validate.<name>")`
and `from scripts.validate import <name>` keep resolving.
"""

import argparse
import os
import shutil  # noqa: F401  (back-compat: patch("validate.shutil.which") test target; global module identity)
import subprocess  # noqa: F401  (back-compat: patch("validate.subprocess.run") test target; global module identity)
import sys
import time
from pathlib import Path as _Path

# Some callers invoke this file as a direct script path (`python scripts/validate.py`,
# e.g. scripts/execute_recommendation.py's [VALIDATE] finalize step) rather than as a
# module (`python -m scripts.validate`); the former does not put the repo root on
# sys.path, so `scripts` would not be importable as a top-level package. Ensure it is,
# before importing scripts.checks.* below.
_REPO_ROOT = _Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.checks import _common, registry  # noqa: E402

# Facade re-exports: shared primitives (back-compat for `from scripts.validate import ROOT` etc.
# and for `patch("validate.ROOT"/"validate.run"/"validate.PYTHON"/"validate.invoke_step"/
# "validate.get_changed_files")`). Scaffolding below uses the qualified _common.* form so that
# scripts.checks._common is the single interception point for every caller, extracted or not.
from scripts.checks._common import PYTHON, ROOT, get_changed_files, invoke_step, run  # noqa: F401,E402
from scripts.checks._scaffolding import (  # noqa: F401,E402
    _DQ_FRESHNESS_SECONDS,
    _TERRAFORM_ROOTS,
    _TRANSIENT_CLAUDE_SIGNATURES,
    _TRANSIENT_INIT_SIGNATURES,
    _build_unit_test_cmd,
    _file_budget_breach_rec,
    _file_budget_bypass_rec,
    _terraform_init_with_retry,
    ensure_fresh_dq_results,
    run_coverage_check,
    run_dependency_checks,
    run_lint_checks,
    run_precommit_checks,
    run_pytest_diff,
    run_terraform_checks,
    run_terraform_creds_free,
)

# --- Facade re-exports: every extracted check (getattr + `from scripts.validate import X`) ---
from scripts.checks.ci_guards.validate_ci_rca_taxonomy import validate_ci_rca_taxonomy  # noqa: F401,E402
from scripts.checks.ci_guards.validate_ci_rca_trigger import validate_ci_rca_trigger  # noqa: F401,E402
from scripts.checks.ci_guards.validate_ci_workflow_guards import validate_ci_workflow_guards  # noqa: F401,E402
from scripts.checks.ci_guards.validate_claude_p_retry_wrapper import (  # noqa: E402
    _check_claude_p_raw_invocations,  # noqa: F401
    validate_claude_p_retry_wrapper,  # noqa: F401
)
from scripts.checks.ci_guards.validate_workflow_agent_safety import validate_workflow_agent_safety  # noqa: F401,E402
from scripts.checks.contracts._shared import _load_prompt_compliance  # noqa: F401,E402
from scripts.checks.contracts.validate_claude_md_pointer_invariant import (  # noqa: E402
    check_claude_md_pointer_invariant,  # noqa: F401
    validate_claude_md_pointer_invariant,  # noqa: F401
)
from scripts.checks.contracts.validate_contract_drift import validate_contract_drift  # noqa: F401,E402
from scripts.checks.contracts.validate_instruction_architecture_layers import (  # noqa: F401,E402
    validate_instruction_architecture_layers,
)
from scripts.checks.contracts.validate_intent_doc_freeze import validate_intent_doc_freeze  # noqa: F401,E402
from scripts.checks.contracts.validate_no_underscore_instructions import (  # noqa: F401,E402
    validate_no_underscore_instructions,
)
from scripts.checks.contracts.validate_portal_drift import validate_portal_drift  # noqa: F401,E402
from scripts.checks.contracts.validate_prompt_compliance import validate_prompt_compliance  # noqa: F401,E402
from scripts.checks.deps.validate_dependency_graph_freshness import (  # noqa: F401,E402
    validate_dependency_graph_freshness,
)
from scripts.checks.deps.validate_import_contracts import validate_import_contracts  # noqa: F401,E402
from scripts.checks.deps.validate_imports import validate_imports  # noqa: F401,E402
from scripts.checks.deps.validate_lockfile_sync import validate_lockfile_sync  # noqa: F401,E402
from scripts.checks.deps.validate_requirements import validate_requirements  # noqa: F401,E402
from scripts.checks.executor.validate_executor_boundary import (  # noqa: E402
    _EXECUTOR_BOUNDARY_PATTERNS,  # noqa: F401
    _load_boundary_patterns,  # noqa: F401
    validate_executor_boundary,  # noqa: F401
)
from scripts.checks.hygiene.validate_cli_tools_in_prompts import (  # noqa: E402
    _KNOWN_CLI_TOOLS,  # noqa: F401
    _OPTIONAL_CLI_TOOLS,  # noqa: F401
    validate_cli_tools_in_prompts,  # noqa: F401
)
from scripts.checks.hygiene.validate_subprocess_encoding import validate_subprocess_encoding  # noqa: F401,E402
from scripts.checks.hygiene.validate_sys_executable import validate_sys_executable  # noqa: F401,E402
from scripts.checks.iam_tf.validate_authority_budget import validate_authority_budget  # noqa: F401,E402
from scripts.checks.iam_tf.validate_environment_taxonomy import validate_environment_taxonomy  # noqa: F401,E402
from scripts.checks.iam_tf.validate_iam_runner_policy import validate_iam_runner_policy  # noqa: F401,E402
from scripts.checks.iam_tf.validate_terraform_try import _is_inside_try, validate_terraform_try  # noqa: F401,E402
from scripts.checks.lambda_pkg.validate_lambda_bundle_completeness import (  # noqa: F401,E402
    validate_lambda_bundle_completeness,
)
from scripts.checks.lambda_pkg.validate_lambda_deploy_gating import validate_lambda_deploy_gating  # noqa: F401,E402
from scripts.checks.lambda_pkg.validate_lambda_manifest_coverage import (  # noqa: F401,E402
    validate_lambda_manifest_coverage,
)
from scripts.checks.lambda_pkg.validate_lambda_manifests import validate_lambda_manifests  # noqa: F401,E402
from scripts.checks.misc.validate_ducklake_version_lockstep import (  # noqa: F401,E402
    validate_ducklake_version_lockstep,
)
from scripts.checks.misc.validate_ghas_probe import validate_ghas_probe  # noqa: F401,E402
from scripts.checks.misc.validate_invariants import validate_invariants  # noqa: F401,E402
from scripts.checks.misc.validate_scheduled_agent_logs import validate_scheduled_agent_logs  # noqa: F401,E402
from scripts.checks.misc.validate_test_coverage import _load_coverage_checker, validate_test_coverage  # noqa: F401,E402
from scripts.checks.ops_governance.check_source_registry import check_source_registry  # noqa: F401,E402
from scripts.checks.ops_governance.validate_decisions_local_writes import (  # noqa: F401,E402
    validate_decisions_local_writes,
)
from scripts.checks.ops_governance.validate_dq_manifest_gate import validate_dq_manifest_gate  # noqa: F401,E402
from scripts.checks.ops_governance.validate_field_semantics_drift import (  # noqa: F401,E402
    validate_field_semantics_drift,
)
from scripts.checks.ops_governance.validate_outbox_staleness import validate_outbox_staleness  # noqa: F401,E402
from scripts.checks.ops_governance.validate_pydantic_yaml_drift import (  # noqa: E402
    _check_drift_for_table,  # noqa: F401
    validate_pydantic_yaml_drift,  # noqa: F401
)
from scripts.checks.ops_governance.validate_rec_relevance_contract import (  # noqa: F401,E402
    validate_rec_relevance_contract,
)
from scripts.checks.ops_governance.validate_rec_write_paths import validate_rec_write_paths  # noqa: F401,E402
from scripts.checks.ops_governance.validate_recommendations_schema import (  # noqa: F401,E402
    validate_recommendations_schema,
)
from scripts.checks.ops_governance.validate_warehouse_write_sources import (  # noqa: F401,E402
    validate_warehouse_write_sources,
)
from scripts.checks.product.trading.validate_broker_env_reads import validate_broker_env_reads  # noqa: F401,E402
from scripts.checks.prompts.validate_prompt_files import KNOWN_MODELS, validate_prompt_files  # noqa: F401,E402
from scripts.checks.roadmap.check_graduation_guard import (  # noqa: E402
    _check_graduation_guard,  # noqa: F401
    _extract_enforced_map,  # noqa: F401
)
from scripts.checks.roadmap.validate_candidate_decision_ratification import (  # noqa: F401,E402
    validate_candidate_decision_ratification,
)
from scripts.checks.roadmap.validate_plan_documents import validate_plan_documents  # noqa: F401,E402
from scripts.checks.roadmap.validate_platform_roadmap import validate_platform_roadmap  # noqa: F401,E402
from scripts.checks.roadmap.validate_product_roadmap import validate_product_roadmap  # noqa: F401,E402
from scripts.checks.sloc._shared import (  # noqa: E402
    _BRANCH_TYPES,  # noqa: F401
    _CC_LIMIT,  # noqa: F401
    _SLOC_EXCLUDE_DIRS,  # noqa: F401
    _SLOC_LIMIT,  # noqa: F401
    _WAIVER_PATTERN,  # noqa: F401
)
from scripts.checks.sloc.cc_limits import validate_cc_limits  # noqa: F401,E402
from scripts.checks.sloc.complexity import validate_complexity  # noqa: F401,E402
from scripts.checks.sloc.sloc_limits import (  # noqa: E402
    _load_sloc_budgets,  # noqa: F401
    _update_sloc_budgets,
    validate_sloc_limits,  # noqa: F401
)
from scripts.checks.verification.validate_differential_gate_baseline import (  # noqa: F401,E402
    validate_differential_gate_baseline,
)
from scripts.checks.verification.validate_hermeticity_flags import (  # noqa: E402
    _UNIT_TEST_HERMETICITY_FLAGS,  # noqa: F401
    validate_hermeticity_flags,  # noqa: F401
)
from scripts.checks.verification.validate_verification_harness import validate_verification_harness  # noqa: F401,E402
from scripts.checks.verification.validate_verification_registry import (  # noqa: F401,E402
    validate_verification_registry,
)
from scripts.checks.verification.validate_verifier_hermeticity import (  # noqa: E402
    _dotted_name_from_attr,  # noqa: F401
    _verifier_is_non_hermetic,  # noqa: F401
    validate_verifier_hermeticity,  # noqa: F401
)
from scripts.checks.verification.validate_verifier_same_pr_guard import (  # noqa: E402
    _extract_verifier_covers,  # noqa: F401
    validate_verifier_same_pr_guard,  # noqa: F401
)

_FAST_TIER_BUDGET_SECONDS = 300


def _dispatch_check(name: str, failed: list[str]) -> None:
    """Resolve a registered check by name via this module's own namespace and call it.

    Uses globals() (equivalent to getattr(sys.modules[__name__], name)) rather than a
    captured function reference, so `patch("validate.<name>")` continues to intercept.
    """
    globals()[name](failed)


def run_python_checks(failed: list[str]) -> None:
    """Dispatch the ENTIRE full (default) tier by iterating registry.full_sequence() -- every
    check and non-check scaffold step, from lint through the all-files precommit run. This is
    the sole source of full-tier order: main() calls this once and does not hand-dispatch any
    of these steps itself, so registry.py stays the single place that adding/reordering a
    full-tier check touches.
    """

    def _scaffold_lint() -> None:
        run_lint_checks(failed)

    def _scaffold_unit_tests() -> None:
        _common.invoke_step("Unit tests + coverage", _build_unit_test_cmd(), failed)

    def _scaffold_mypy_full() -> None:
        print("\n=== mypy (informational) ===")
        result = _common.run([_common.PYTHON, "-m", "mypy", "src/"], cwd=_common.ROOT)
        if result.returncode != 0:
            print("mypy: type errors found (informational - not blocking). Fix progressively.")

    def _scaffold_terraform_checks() -> None:
        run_terraform_checks(failed)

    def _scaffold_dependency_health() -> None:
        run_dependency_checks()

    def _scaffold_ensure_fresh_dq() -> None:
        ensure_fresh_dq_results(failed)

    def _scaffold_precommit_all_files() -> None:
        run_precommit_checks(failed, all_files=True)

    scaffold_fns = {
        "lint": _scaffold_lint,
        "unit_tests": _scaffold_unit_tests,
        "mypy_full": _scaffold_mypy_full,
        "terraform_checks": _scaffold_terraform_checks,
        "dependency_health": _scaffold_dependency_health,
        "ensure_fresh_dq": _scaffold_ensure_fresh_dq,
        "precommit_all_files": _scaffold_precommit_all_files,
    }

    for step in registry.full_sequence():
        if step.kind == "check":
            _dispatch_check(step.name, failed)
        else:
            scaffold_fns[step.name]()


def main() -> None:
    # Recursion guard: validate.py spawns pytest, which may collect tests that
    # import/call validate.py again.  _VALIDATE_DEPTH prevents infinite loops.
    depth = int(os.environ.get("_VALIDATE_DEPTH", "0"))
    if depth >= 1:
        print(f"[SKIP] validate.py recursion detected (depth={depth}). Exiting.")
        sys.exit(0)
    os.environ["_VALIDATE_DEPTH"] = str(depth + 1)

    parser = argparse.ArgumentParser(description="Local CI validation. Run before every commit.")
    parser.add_argument(
        "--pre",
        action="store_true",
        help="Run diff-aware lint/format/mypy/pytest + prompt validation only. Skips terraform and dependencies. "
        "Use for per-step validation during implementation. Subject to a 5-minute wall-clock budget.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Report scope files lacking verifier coverage (advisory; exits 0 unconditionally).",
    )
    parser.add_argument(
        "--terraform-only",
        action="store_true",
        help="Run ONLY the credential-free terraform gate (init -backend=false + validate + fmt -check) "
        "for terraform/ and terraform/personal/. Used by the terraform-validate CI job; no AWS creds needed.",
    )
    parser.add_argument(
        "--ignore-budget",
        action="store_true",
        help="Skip the 5-minute fast-tier budget assertion. Emergency escape hatch only. "
        "Disallowed when CI=true. Bypass is audited via ops_data_portal.",
    )
    parser.add_argument(
        "--ignore-budget-reason",
        default=None,
        metavar="TEXT",
        help="Optional reason for bypassing the budget assertion (captured in the bypass audit rec).",
    )
    parser.add_argument(
        "--update-sloc-budgets",
        action="store_true",
        help="Regenerate config/sloc_budgets.yaml from the current tree (downward-only ratchet). "
        "Lowers shrunk budgets, seeds newly-oversized files, drops files now <=500. Never raises an existing budget.",
    )
    args = parser.parse_args()

    # CI guard: --ignore-budget is forbidden in CI environments
    if args.ignore_budget and os.environ.get("CI") == "true":
        print("[ERROR] --ignore-budget cannot be used in CI. The escape hatch is for local sessions only.")
        sys.exit(1)

    # Branch guard (skip in CI to allow running from CI environments)
    if os.environ.get("CI") != "true":
        result = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        if result.stdout.strip() == "main":
            print("\n[ERROR] validate.py refused to run on 'main'.")
            print("Create a feature branch first: git checkout -b agent/{slug}")
            sys.exit(1)

    failed: list[str] = []

    # --coverage: advisory verifier-coverage report, then exit 0
    if args.coverage:
        run_coverage_check()
        sys.exit(0)

    # --update-sloc-budgets: regenerate the SLOC budget registry and exit
    if args.update_sloc_budgets:
        _update_sloc_budgets()
        sys.exit(0)

    # --terraform-only: creds-free terraform gate for both roots (CI terraform-validate job)
    if args.terraform_only:
        run_terraform_creds_free(failed)
        print("\n=== Validation Summary (scope: terraform-only) ===")
        if not failed:
            print("All checks passed.")
            sys.exit(0)
        print("Failed checks:")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)

    # --pre: diff-aware lint/format/mypy/picked-pytest + prompt validation, with 5-min budget
    if args.pre:
        _t0 = time.monotonic()
        print("Pre mode: diff-aware lint/format/mypy/pytest and prompt validation.")

        changed = _common.get_changed_files()
        diff_manifest = list(changed)
        changed_py = [f for f in changed if f.endswith(".py")]
        # Select changed test files from the same get_changed_files() result that drives the rest of
        # --pre. Passing explicit paths removes the dependence on pytest-picked's independent
        # branch-diff, which collapses to 0 tests in GitHub Actions' detached-HEAD PR checkout
        # (PR #334, job 84147146286 -- "collected 0 items / no tests ran" yet all-passed).
        # Decision 55 backstop: exit 5 (0 collected) while changed test files are present is a
        # contradiction -- redden the gate loudly rather than swallowing it as the old (0,5)
        # whitelist did.
        # Accepted edge case: a changed test file containing ONLY integration-marked tests will
        # trip this backstop because -m "not integration" deselects all; resolve by not gating
        # all-integration files behind the unit tier.
        import re as _re

        changed_tests = [f for f in changed if _re.match(r"tests/.*test_[^/]+\.py$", f)]

        def _scaffold_lint() -> None:
            run_lint_checks(failed, files=changed)

        def _scaffold_precommit_changed() -> None:
            run_precommit_checks(failed, all_files=False, files=changed)

        def _scaffold_mypy_diff() -> None:
            if changed_py:
                print("\n=== Type check (mypy -- informational) ===")
                mypy_result = _common.run(
                    [_common.PYTHON, "-m", "mypy", "--follow-imports=silent"] + changed_py, cwd=_common.ROOT
                )
                if mypy_result.returncode != 0:
                    print("mypy: type errors found in changed files (informational - not blocking). Fix progressively.")

        def _scaffold_pytest_diff() -> None:
            run_pytest_diff(changed_tests, failed)

        def _scaffold_coverage_report() -> None:
            run_coverage_check(changed)

        def _scaffold_budget_assertion() -> None:
            elapsed = time.monotonic() - _t0
            if args.ignore_budget:
                _file_budget_bypass_rec(elapsed, diff_manifest, args.ignore_budget_reason)
                print(f"\nBudget assertion skipped (--ignore-budget). Elapsed: {elapsed / 60:.1f} min.")
            elif elapsed > _FAST_TIER_BUDGET_SECONDS:
                _file_budget_breach_rec(elapsed, diff_manifest, None)
                print(
                    f"\nERROR: Fast tier exceeded budget (5 min). Elapsed: {elapsed / 60:.1f} min.\n"
                    "This tier has grown beyond its design contract. Either:\n"
                    "  1. Move the slow check to the full tier, or\n"
                    "  2. Optimise the check, or\n"
                    "  3. Open a planning session to revise this budget (requires Decision Record)."
                )
                sys.exit(1)

        scaffold_fns = {
            "lint": _scaffold_lint,
            "precommit_changed": _scaffold_precommit_changed,
            "mypy_diff": _scaffold_mypy_diff,
            "pytest_diff": _scaffold_pytest_diff,
            "coverage_report": _scaffold_coverage_report,
            "budget_assertion": _scaffold_budget_assertion,
        }

        for step in registry.pre_sequence():
            if step.kind == "check":
                _dispatch_check(step.name, failed)
            else:
                scaffold_fns[step.name]()

        print("\n=== Validation Summary (scope: pre) ===")
        if not failed:
            print("All checks passed.")
            sys.exit(0)
        else:
            print("Failed checks:")
            for f in failed:
                print(f"  - {f}")
            print("\nFix all failures before committing.")
            sys.exit(1)

    scope = "all"

    # Full (default) tier: run_python_checks() dispatches the ENTIRE registry.full_sequence()
    # (every check + scaffold step, lint through the all-files precommit run) -- see its
    # docstring. There is no separate hand-dispatched block here; registry.py is the sole
    # source of full-tier order.
    run_python_checks(failed)

    print(f"\n=== Validation Summary (scope: {scope}) ===")
    if not failed:
        print("All checks passed.")
        sys.exit(0)
    else:
        print("Failed checks:")
        for f in failed:
            print(f"  - {f}")
        print("\nFix all failures before committing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
