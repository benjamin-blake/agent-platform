# complexity-waiver: decision-43
#!/usr/bin/env python3
"""Local CI validation script. Run before every commit.

Runs validation checks that mirror the GitHub Actions CI pipeline.
Default (no flags) runs the full check suite. Use --pre for fast lint/format
checks only during implementation.

Thin CLI (Decision 104, dispatch rewired to per-domain manifests by Decision 169): every check
lives in scripts/checks/<domain>/ and is tagged in the scripts/checks/registry.py check registry,
dispatched via registry.resolve(name) -- never a facade re-export in this file. This file retains
only the argparse surface, the recursion/branch guards, the fast-tier budget assertion, the
non-check scaffolding steps (lint, precommit, mypy, explicit pytest, unit-test invoke_step,
dependency/terraform gates), and re-exports of the shared _common/_scaffolding primitives (back-compat
for `patch("validate.<primitive>")` and `from scripts.validate import <primitive>`).
"""

import argparse
import fnmatch
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

from scripts.checks import _common, registry, validation_result  # noqa: E402

# Facade re-exports: shared primitives (back-compat for `from scripts.validate import ROOT` etc.
# and for `patch("validate.ROOT"/"validate.run"/"validate.PYTHON"/"validate.invoke_step"/
# "validate.get_changed_files")`). Scaffolding below uses the qualified _common.* form so that
# scripts.checks._common is the single interception point for every caller, extracted or not.
from scripts.checks._common import PYTHON, ROOT, get_changed_files, get_status_aware_diff, invoke_step, run  # noqa: F401,E402
from scripts.checks._scaffolding import (  # noqa: F401,E402
    _DQ_FRESHNESS_SECONDS,
    _TERRAFORM_ROOTS,
    _TRANSIENT_CLAUDE_SIGNATURES,
    _TRANSIENT_INIT_SIGNATURES,
    _build_unit_test_cmd,
    _file_budget_breach_rec,
    _file_budget_bypass_rec,
    _mirror_budget_notice_to_summary,
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
from scripts.checks.sloc.sloc_limits import _update_sloc_budgets  # noqa: E402

_FAST_TIER_BUDGET_SECONDS = 300

# Derived guardrail, not a second tier budget (Decision 153): pr-validate's 30-min job
# timeout (.github/workflows/ci.yml) minus a ~5-min diagnostic margin, on the fast tier's
# own elapsed clock (job clock additionally includes checkout/pip). Re-derive if
# timeout-minutes changes; the fast tier's sole design budget is _FAST_TIER_BUDGET_SECONDS.
_FORCED_FULL_SUITE_CEILING_SECONDS = 1500


def _dispatch_check(name: str, failed: list[str]) -> None:
    """Resolve a registered check by name via registry.resolve() and call it.

    registry.resolve(name) imports the check's DEFINING module and does a late-bound getattr at
    call time (Decision 169, amending Decision 104's namespace-dict dispatch) -- so
    `patch("<the check's defining module>.<name>", ...)` continues to intercept, and the resolved
    callable is never cached across dispatches.
    """
    validation_result.dispatch_recording(name, failed, registry.resolve(name))


def _pre_glob_match(path: str, glob: str) -> bool:
    """fnmatch-based match of a single repo-relative path against a single pre_globs pattern.

    fnmatch's `*` already crosses path separators (unlike pathlib/glob.glob's non-recursive
    `*`), so a `**` segment (e.g. "docs/plans/**") matches any depth without special-casing.
    """
    return fnmatch.fnmatch(path, glob)


def _should_run_in_pre(pre_globs: tuple[str, ...] | None, changed_paths, derivation_ok: bool) -> bool:
    """Decide whether a --pre gated check should run (VTS-09, dec-55/dec-135/dec-153 fail-closed).

    True (run) when: the check is ungated (pre_globs is None), the diff derivation failed or
    returned something unexpected (derivation_ok is False), the derived changed-path set is
    empty (a no-diff or derivation-blind-spot branch state), or at least one changed path
    matches one of the check's globs. False (skip) ONLY on a successful, non-empty derivation
    with zero matches -- never silently skip on doubt.
    """
    if pre_globs is None or not derivation_ok or not changed_paths:
        return True
    return any(_pre_glob_match(path, glob) for path in changed_paths for glob in pre_globs)


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

    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("[SKIP] validate.py invoked from within a pytest run (PYTEST_CURRENT_TEST set). Exiting.")
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Local CI validation. Run before every commit.")
    parser.add_argument(
        "--pre",
        action="store_true",
        help="Run diff-aware lint/format/mypy/pytest + prompt validation only. Skips terraform and dependencies. "
        "Use for per-step validation during implementation. Subject to a 5-minute wall-clock budget.",
    )
    parser.add_argument(
        "--verifier-coverage",
        "--coverage",
        dest="verifier_coverage",
        action="store_true",
        help="Report scope files lacking verifier coverage (advisory; exits 0 unconditionally). "
        "--coverage is a deprecated alias for --verifier-coverage.",
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
        help="Requires a feature branch (refused on main, like every validate.py invocation). "
        "Regenerate config/sloc_budgets.yaml from the current tree (downward-only ratchet): "
        "lowers shrunk budgets, drops files now <=500. Never raises an existing budget and never "
        "seeds a newly-oversized file (Decision 128) -- decompose it, or register it manually with "
        "a `# raise-approved: dec-NNN` marker.",
    )
    args = parser.parse_args()

    full_started_at: str | None = None
    if not any((args.pre, args.verifier_coverage, args.terraform_only, args.update_sloc_budgets)):
        full_started_at = validation_result.utc_now()
        validation_result.clear()

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

    # --verifier-coverage: advisory verifier-coverage report, then exit 0 (--coverage: deprecated alias)
    if args.verifier_coverage:
        if "--coverage" in sys.argv:
            print("[DEPRECATED] --coverage is a deprecated alias; use --verifier-coverage instead.")
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

    # --pre: diff-aware lint/format/mypy/affected-set pytest (Decision 135) + prompt validation, with 5-min budget
    if args.pre:
        _t0 = time.monotonic()
        print("Pre mode: diff-aware lint/format/mypy/pytest and prompt validation.")

        changed = _common.get_changed_files()
        diff_manifest = list(changed)
        changed_py = [f for f in changed if f.endswith(".py")]
        # Live, cacheless, strictly-additive affected-set selection (Decision affected-set-
        # selection, amends Decision 73's 2nd amendment): upgrades the edited-set (test files
        # literally in the diff) to a per-run affected-set (tests AFFECTED by the diff), so a
        # source-only PR -- or a test broken by a change it does not itself contain -- is
        # caught pre-merge. Feeds the SAME pytest_diff scaffold below (preferred inline path --
        # touches neither scripts/checks/registry.py nor the frozen pre-sequence scaffold
        # baseline). status_entries is a SEPARATE diff surface from `changed` above (includes
        # deletions + untracked new files, rec-2638) -- get_changed_files()'s own contract for
        # its existing callers (lint/mypy/precommit/coverage) is unchanged. Defensively unioned
        # with `changed` (assumed status "M") so the two independent git reads never silently
        # diverge on which paths are in scope for selection.
        #
        # Deferred (function-scope) import: scripts.checks.deps.affected_tests imports networkx
        # at its own module scope, and this is the ONLY place these two names are used --
        # importing eagerly at validate.py's module scope would break --terraform-only, whose CI
        # job installs only pyyaml+pydantic (see the facade-import block's comment above).
        from scripts.checks.deps.affected_tests import derive_affected_tests, emit_manifest  # noqa: PLC0415

        status_entries = _common.get_status_aware_diff()
        _status_paths = {path for _, path in status_entries}
        for f in changed:
            if f not in _status_paths:
                status_entries.append(("M", f))
        _affected_selection = derive_affected_tests(status_entries, repo_root=_common.ROOT)
        changed_tests = _affected_selection["selected"]
        emit_manifest(_affected_selection["manifest"])

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

        def _scaffold_verifier_coverage_report() -> None:
            run_coverage_check(changed)

        phase_times: dict[str, float] = {}

        def _scaffold_budget_assertion() -> None:
            elapsed = time.monotonic() - _t0
            dominant_phase = max(phase_times, key=lambda phase: phase_times[phase]) if phase_times else None
            if args.ignore_budget:
                _file_budget_bypass_rec(elapsed, diff_manifest, args.ignore_budget_reason)
                print(f"\nBudget assertion skipped (--ignore-budget). Elapsed: {elapsed / 60:.1f} min.")
            elif elapsed > _FAST_TIER_BUDGET_SECONDS:
                # Decision 153: a root-conftest change deterministically forces full-suite scope
                # (Decision 135/VTS-03) and is a self-identified, already-diagnosed cause of the
                # breach -- not drift. Narrow the hard-fail to exactly the non-forced case; a
                # forced run is still bounded by the derived ceiling below. Fail-closed read:
                # _empty_manifest defaults full_suite_forced to False, so any derivation-failure
                # fallback still hard-fails.
                forced = bool(_affected_selection["manifest"].get("full_suite_forced", False))
                if forced and elapsed <= _FORCED_FULL_SUITE_CEILING_SECONDS:
                    _mirror_budget_notice_to_summary(
                        "Fast-tier budget waived (forced full-suite scope)",
                        "budget waived: full-suite scope forced by root-conftest change. "
                        f"Elapsed: {elapsed / 60:.1f} min (forced-run ceiling: "
                        f"{_FORCED_FULL_SUITE_CEILING_SECONDS / 60:.0f} min). Dominant phase: "
                        f"{dominant_phase or 'unknown'}. No breach rec filed -- this is a "
                        "deterministic, already-diagnosed full-suite run, not drift.",
                    )
                elif forced:
                    _mirror_budget_notice_to_summary(
                        "Fast-tier forced-run ceiling breached",
                        "ERROR: forced full-suite run exceeded the forced-run ceiling "
                        f"({_FORCED_FULL_SUITE_CEILING_SECONDS / 60:.0f} min). Elapsed: "
                        f"{elapsed / 60:.1f} min. Dominant phase: {dominant_phase or 'unknown'}.\n"
                        "The forced full suite itself is now the problem, not the gate -- "
                        "open a planning session (Decision 153 reversal condition (b)).",
                    )
                    sys.exit(1)
                else:
                    _file_budget_breach_rec(elapsed, diff_manifest, dominant_phase)
                    print(
                        f"\nERROR: Fast tier exceeded budget (5 min). Elapsed: {elapsed / 60:.1f} min. "
                        f"Dominant phase: {dominant_phase or 'unknown'}.\n"
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
            "verifier_coverage_report": _scaffold_verifier_coverage_report,
            "budget_assertion": _scaffold_budget_assertion,
        }

        # pre_globs gate derivation (VTS-09): reuse the already-built status-aware diff:
        # fail-closed on any derivation error (dec-135) -- an exception here must never
        # silently skip a gated check, so _gate_derivation_ok flips to False and
        # _should_run_in_pre runs everything regardless of glob match.
        try:
            _gate_changed_paths = {path for _, path in status_entries}
            _gate_derivation_ok = True
        except Exception as exc:
            _gate_changed_paths = set()
            _gate_derivation_ok = False
            print(f"pre_globs: diff derivation failed ({exc}); running all gated checks (fail-closed).")

        for step in registry.pre_sequence():
            step_t0 = time.monotonic()
            if step.kind == "check":
                if _should_run_in_pre(step.pre_globs, _gate_changed_paths, _gate_derivation_ok):
                    _dispatch_check(step.name, failed)
                else:
                    print(f"skipped-by-glob: {step.name}")
            else:
                scaffold_fns[step.name]()
            phase_times[step.name] = time.monotonic() - step_t0

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
        validation_result.write_completed_visible(
            started_at=full_started_at or validation_result.utc_now(), exit_code=0, failed_checks=[]
        )
        sys.exit(0)
    else:
        print("Failed checks:")
        for f in failed:
            print(f"  - {f}")
        print("\nFix all failures before committing.")
        validation_result.write_completed_visible(
            started_at=full_started_at or validation_result.utc_now(), exit_code=1, failed_checks=failed
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
