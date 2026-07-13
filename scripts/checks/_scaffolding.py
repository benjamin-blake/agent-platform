"""CLI scaffolding steps that are not registered checks (Decision 104).

These implement the non-check scaffolding steps referenced by
scripts/checks/registry.py's pre_sequence()/full_sequence() (lint, precommit,
dependency health, DQ freshness, verifier-coverage report, budget-breach/bypass
rec filing, and the unit-test command builder); the terraform gate lives in
scripts/checks/_terraform.py and is re-exported here for facade back-compat. They stay
outside the check registry (no @register decorator, not a `validate_*(failed)`
uniform check signature in every case) but outside scripts/validate.py too, so
the CLI entrypoint stays thin. scripts/validate.py imports and re-exports all
of these for back-compat (`patch("validate.<name>")` / `from scripts.validate
import <name>` keep resolving).
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import time
from pathlib import Path

from scripts.checks import _common
from scripts.checks._terraform import (  # noqa: F401
    _TERRAFORM_ROOTS,
    _TRANSIENT_INIT_SIGNATURES,
    _terraform_init_with_retry,
    run_terraform_checks,
    run_terraform_creds_free,
)

# Transient Claude API error signatures; parity with _is_transient() in scripts/ci/claude_p_retry.sh.
# Distinct from _TRANSIENT_INIT_SIGNATURES (terraform registry 5xx). Decision 73, Decision 92.
_TRANSIENT_CLAUDE_SIGNATURES: tuple[str, ...] = ("500", "502", "503", "API Error: 5", "Internal server error", "overloaded")

_DQ_FRESHNESS_SECONDS = 3600  # 1 hour

# Parallelism + per-test timeout for both --pre pytest-diff invocations (primary and reactive
# survivor re-run). Cap (60s) is comfortably above the slowest legitimate unit (~3s) and well
# under the 300s fast-tier budget.
#
# rec-2653: a fixed integer --randomly-seed overrides pyproject.toml's addopts
# "--randomly-seed=last" for these xdist-parallel invocations only, so every -n auto worker
# resolves the same collection order on a cold .pytest_cache. "last" resolves inconsistently
# across workers on GH-hosted runners, producing "Different tests were collected between gw1
# and gwN". pyproject.toml itself is untouched (local-dev re-run ergonomics), and -n auto is
# untouched (worker count is not the defect).
_PYTEST_RANDOMLY_SEED = 20260710
_PYTEST_FLAGS = [
    "-n",
    "auto",
    "--timeout",
    "60",
    "--timeout-method=thread",
    f"--randomly-seed={_PYTEST_RANDOMLY_SEED}",
]


def run_precommit_checks(failed: list[str], *, all_files: bool, files: list[str] | None = None) -> None:
    """Run the pre-commit hook suite (detect-secrets, shape denylist, file hygiene).

    pre-commit is the single home for detect-secrets and the shape-based
    never-commit identifier denylist. Routing it through validate.py keeps
    validate.py the single source of truth: the same hooks run in the --pre edit
    loop, the pr-validate CI gate, and the main-validate full tier -- so a failing
    detect-secrets result can no longer merge unseen (it reddens the authoritative
    gate the way every other check does, instead of only the advisory pre_commit
    workflow that push-to-main never blocked on).

    no-commit-to-branch is skipped via SKIP: it is a commit-time guard already
    covered by .claude/hooks/never_on_main.py, and it would always fail on the
    push-to-main main-validate run (which legitimately runs on the main branch).
    """
    name = "pre-commit hooks"
    if importlib.util.find_spec("pre_commit") is None:
        print(f"\n=== {name} ===\nWARNING: pre-commit not installed; skipping (install requirements-dev.txt).")
        return
    cmd = [_common.PYTHON, "-m", "pre_commit", "run", "--show-diff-on-failure", "--color", "never"]
    if all_files:
        cmd.append("--all-files")
    else:
        target = files if files is not None else _common.get_changed_files()
        if not target:
            print(f"\n=== {name} ===\nNo changed files vs origin/main; skipping.")
            return
        cmd += ["--files", *target]
    print(f"\n=== {name} ===")
    env = {**os.environ, "SKIP": "no-commit-to-branch"}
    result = _common.run(cmd, cwd=_common.ROOT, env=env)
    if result.returncode != 0:
        failed.append(name)


def run_lint_checks(failed: list[str], files: list[str] | None = None) -> None:
    if files is not None and not files:
        return
    targets: list[str] = [f for f in files if f.endswith(".py")] if files is not None else ["src/", "tests/"]
    if not targets:
        return
    _common.invoke_step("Lint (ruff check)", [_common.PYTHON, "-m", "ruff", "check"] + targets, failed)
    _common.invoke_step("Format check (ruff format)", [_common.PYTHON, "-m", "ruff", "format", "--check"] + targets, failed)


def _file_budget_breach_rec(elapsed_s: float, diff_manifest: list[str], dominant_phase: str | None) -> None:
    elapsed_min = elapsed_s / 60
    manifest_summary = ", ".join(diff_manifest[:20]) + ("..." if len(diff_manifest) > 20 else "")

    if os.environ.get("CI") == "true":
        # CI-guard (Decision 84 I-4): the pr-validate CI job installs requirements-fast.txt (no
        # python-ulid) and has no AWS credentials, so file_rec's portal write can never complete
        # there -- it previously raised a swallowed ModuleNotFoundError inside the bare except
        # below. Skip the write and print the full diagnostic LOUDLY instead: this is a no-op-plus
        # -loud-log, never a silent `if CI: return` (Decision 55) and never a buffered/replayed
        # outbox entry (Decision 84 I-4 -- nothing is staged for later delivery).
        message = (
            f"WARNING: fast-tier budget breach ({elapsed_min:.1f}m, limit 5m): dominant_phase="
            f"{dominant_phase or 'unknown'}, diff ({len(diff_manifest)} files): {manifest_summary}. Rec NOT filed (CI)."
        )
        print(message, file=sys.stderr)
        # CI-native diagnosability (no portal, no outbox -- Decision 84 I-4): mirror to the job's
        # step summary; falls back to the stderr print above if unset.
        if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"\n## Fast-tier budget breach\n\n{message}\n")
        return

    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        branch = branch_r.stdout.strip() or "unknown"
        context = (
            f"Fast-tier budget breach: {elapsed_min:.1f} min elapsed (limit 5 min). "
            f"Branch: {branch}. Dominant phase: {dominant_phase or 'unknown'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Investigate which check caused the overrun and move it to the full tier or optimise it."
        )
        file_rec(
            {
                "title": f"Fast-tier budget breach ({elapsed_min:.1f} min) on {branch}",
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_breach",
                "effort": "S",
                "priority": "Medium",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(
            f"WARNING: budget breach rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )


def _file_budget_bypass_rec(elapsed_s: float | None, diff_manifest: list[str], reason: str | None) -> None:
    manifest_summary = ", ".join(diff_manifest[:20]) + ("..." if len(diff_manifest) > 20 else "")
    elapsed_part = f"{elapsed_s / 60:.1f} min" if elapsed_s is not None else "unknown"

    if os.environ.get("CI") == "true":
        # Defensive-only: validate.py's CI guard already hard-rejects --ignore-budget when
        # CI=="true" before this helper can be reached in the integrated flow. Kept for parity
        # with _file_budget_breach_rec and to cover any direct/test invocation (Decision 55: no
        # silent skip, never a buffered outbox -- Decision 84 I-4).
        print(
            f"WARNING: fast-tier budget bypass rec NOT filed (CI environment, no portal access): "
            f"Elapsed: {elapsed_part}. Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}.",
            file=sys.stderr,
        )
        return

    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        branch = branch_r.stdout.strip() or "unknown"
        context = (
            f"Fast-tier budget assertion bypassed via --ignore-budget on branch {branch}. "
            f"Elapsed: {elapsed_part}. Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Repeated bypass (>= 3 in 7 days) triggers a soft alert in session_preflight."
        )
        file_rec(
            {
                "title": f"Fast-tier budget bypassed on {branch}",
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_bypass",
                "effort": "S",
                "priority": "Low",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(
            f"WARNING: budget bypass rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )


def _build_unit_test_cmd() -> list[str]:
    """Return the pytest command for the 'Unit tests + coverage' step."""
    return [
        _common.PYTHON,
        "-m",
        "pytest",
        "tests/",
        "-v",
        "-m",
        "not integration",
        "--cov=src",
        "--cov-report=term-missing",
        "--disable-socket",
        "--randomly-seed=last",
    ]


def run_dependency_checks() -> None:
    print("\n=== Dependency health -- CVE scan (informational) ===")
    try:
        result = _common.run(["pip-audit", "--strict"], cwd=_common.ROOT)
        if result.returncode != 0:
            print("pip-audit: vulnerabilities found (see above)")
    except FileNotFoundError:
        print("pip-audit not installed. Run: pip install pip-audit")

    print("\n=== Dependency health -- outdated packages (informational) ===")
    try:
        _common.run(["pip", "list", "--outdated"], cwd=_common.ROOT)
    except FileNotFoundError:
        print("Could not check outdated packages.")


def ensure_fresh_dq_results(failed: list[str]) -> None:
    """Auto-invoke data_quality_runner if logs/debug/dq-latest.json is missing or stale.

    Called during the presubmit tier so the DQ verifier sees fresh data instead
    of SKIPPING on staleness or absence.

    Decision 57: when SSO is unavailable, prints an actionable message and skips
    rather than crashing.
    """
    print("\n=== Ensure fresh DQ results ===")

    dq_file = _common.ROOT / "logs" / "debug" / "dq-latest.json"

    if dq_file.exists():
        age_seconds = time.time() - dq_file.stat().st_mtime
        if age_seconds <= _DQ_FRESHNESS_SECONDS:
            print(f"DQ cache fresh ({age_seconds / 60:.1f}m old) -- skipping data_quality_runner.")
            return
        print(f"DQ cache stale ({age_seconds / 3600:.1f}h old) -- re-running data_quality_runner.")
    else:
        print("DQ cache missing -- running data_quality_runner.")

    try:
        import boto3

        from scripts.aws_profile import resolve_aws_profile

        profile = resolve_aws_profile(default="agent_platform")
        boto3.Session(profile_name=profile).client("sts", region_name="eu-west-2").get_caller_identity()
    except Exception:
        print(
            "AWS credentials not available -- skipping data_quality_runner auto-invoke. "
            "Ensure AWS credentials are configured to enable DQ refresh (Decision 57)."
        )
        return

    _common.invoke_step("Data quality runner", [_common.PYTHON, "-m", "scripts.data_quality_runner"], failed)


def run_coverage_check(changed_files: list[str] | None = None) -> None:
    """Print scope files not covered by any registered verifier (advisory only).

    Wave 1 of INTENT-verification-system.md: surfaces V3 verifier coverage gaps.
    Never appends to the failed list -- exit 0 unconditionally.

    changed_files: reuse an already-computed diff (e.g. the --pre closure's `changed`) to
    avoid a redundant git call; falls back to _common.get_changed_files() when omitted.
    """
    print("\n=== Verifier coverage report (advisory) ===")
    changed = changed_files if changed_files is not None else _common.get_changed_files()
    if not changed:
        print("No changed files detected on this branch -- coverage check has nothing to report.")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.verifiers import check_coverage as _check_coverage

        uncovered = _check_coverage(changed)
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)

    if not uncovered:
        print(f"All scope files covered by at least one verifier ({len(changed)} files checked).")
        return

    print(f"{len(uncovered)} of {len(changed)} scope files lack verifier coverage:")
    for f in uncovered:
        print(f"  - {f}")
    print("\n(Advisory only -- this does not fail the build.)")


# --- Fast-tier heavy-dependency test deferral (rec-2485, Decision 104) ---
#
# requirements-fast.txt (the pr-validate CI job) deliberately omits heavy wheels
# (torch/pandas/numpy/pyarrow/duckdb/etc, ~3GB dominant per .github/workflows/ci.yml:49-59).
# A handful of test files import one of these at module scope, so they can never be
# collected under the fast tier -- that is a structural, not a regression, signal (Google
# TAP / Bazel precedent: SKIPPED-dep-unavailable is distinct from FAILED). The classifier
# below positively identifies that ONE shape and defers it to main-validate (full tier,
# post-merge); every other collection error or test failure stays hard-red (fail-closed).

# Curated dist-name -> import-name aliases for names that differ; default is
# name.lower().replace("-", "_").
_DIST_TO_IMPORT_ALIASES: dict[str, str] = {
    "scikit-learn": "sklearn",
    "psycopg2-binary": "psycopg2",
    "beautifulsoup4": "bs4",
    "python-ulid": "ulid",
}

_NO_MODULE_NAMED_RE = re.compile(r"No module named ['\"]([\w.]+)['\"]")


def _parse_requirement_dist_names(path: Path) -> set[str]:
    """Parse a requirements file into bare distribution names.

    Strips comments, extras (`[...]`), environment markers (after `;`), and version specifiers.
    """
    names: set[str] = set()
    if not path.exists():
        return names
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        line = re.sub(r"\[[^\]]*\]", "", line)
        line = line.split(";", 1)[0].strip()
        name = re.split(r"[<>=!~]", line, maxsplit=1)[0].strip()
        if name:
            names.add(name)
    return names


def _dist_to_import_name(dist_name: str) -> str:
    return _DIST_TO_IMPORT_ALIASES.get(dist_name, dist_name.lower().replace("-", "_"))


def _excluded_heavy_import_names() -> set[str]:
    """Import names deliberately excluded from the fast tier.

    Derived at runtime as (requirements.txt distributions) - (requirements-fast.txt
    distributions), no hard-coded dep list (rec-2485 acceptance).
    """
    full = _parse_requirement_dist_names(_common.ROOT / "requirements.txt")
    fast = _parse_requirement_dist_names(_common.ROOT / "requirements-fast.txt")
    return {_dist_to_import_name(dist) for dist in full - fast}


def _excluded_and_absent(missing: str | None, excluded: set[str]) -> str | None:
    """Return `missing`'s top-level module name if it's a deliberately-excluded, genuinely-absent
    heavy dependency (both conditions checked); otherwise None."""
    if not missing:
        return None
    top_level = missing.split(".")[0]
    if top_level in excluded and importlib.util.find_spec(top_level) is None:
        return top_level
    return None


def _runtime_heavy_dep_defer_reason(test_file: str, excluded: set[str]) -> str | None:
    """Run a single collectible test file for real, in isolation; return the excluded heavy-dep
    name if ANY failure in it traces to a genuinely-absent heavy dependency.

    Catches the shape `--collect-only` cannot see: a dependency imported lazily inside a test or
    the production code it exercises (function scope, not module scope), which only raises
    ModuleNotFoundError when the specific test actually runs. Isolated (one file, one process)
    so a mid-run ModuleNotFoundError in one test cannot leave shared fixture/mock state that
    manifests as unrelated-looking failures in later tests within the same file -- deferring
    the whole file on ANY such hit (not requiring every failure to match) is what makes that
    safe: once the file is known to need a missing dependency, downstream failures in the same
    isolated run aren't independently meaningful.
    """
    result = _common.run(
        [_common.PYTHON, "-m", "pytest", test_file, "-m", "not integration", "-q"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if result.returncode == 0:
        return None
    combined = (result.stdout or "") + (result.stderr or "")
    for match in _NO_MODULE_NAMED_RE.findall(combined):
        found = _excluded_and_absent(match, excluded)
        if found:
            return found
    return None


def partition_changed_tests_by_collectability(changed_tests: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Partition changed test files into (runnable, deferred) via the cheap `--collect-only` pass
    only (Decision 104 / rec-2485; single-execution reshape).

    A file defers when its `--collect-only` root-cause ModuleNotFoundError names a deliberately-
    excluded heavy dependency (in requirements.txt, not requirements-fast.txt) that is genuinely
    absent (`importlib.util.find_spec` is None) -- a module-scope import, visible without running
    any test body. Every other shape -- a real test failure, a non-heavy collection error, or an
    error with no "No module named" line at all -- routes to `runnable`, so the subsequent real
    pytest run reproduces and reddens the genuine failure with full diagnostics (fail-closed).

    A heavy dependency imported LAZILY (function scope, not module scope) is invisible to
    `--collect-only` and is no longer proactively probed here -- `run_pytest_diff` catches that
    shape reactively, only if and after the combined run fails (see `_runtime_heavy_dep_defer_reason`).
    """
    excluded = _excluded_heavy_import_names()
    runnable: list[str] = []
    deferred: list[tuple[str, str]] = []
    for test_file in changed_tests:
        result = _common.run(
            [_common.PYTHON, "-m", "pytest", "--collect-only", "-q", test_file, "-m", "not integration"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=_common.ROOT,
        )
        if result.returncode != 0:
            combined = (result.stdout or "") + (result.stderr or "")
            matches = _NO_MODULE_NAMED_RE.findall(combined)
            missing = _excluded_and_absent(matches[-1], excluded) if matches else None
            if missing:
                deferred.append((test_file, missing))
            else:
                runnable.append(test_file)
            continue
        runnable.append(test_file)
    return runnable, deferred


def _print_deferred_warning(test_file: str, missing_dep: str) -> None:
    print(
        f"\n=== DEFERRED TO FULL TIER (main-validate) ===\n"
        f"{test_file}: cannot run under the fast tier -- dependency '{missing_dep}' is "
        "deliberately excluded from requirements-fast.txt. main-validate (full tier) runs "
        "this file post-merge; a genuine failure there files a source=ci_rca critical rec."
    )


def _reactive_heavy_dep_signature(combined_output: str, excluded: set[str]) -> str | None:
    """Return the first deliberately-excluded, genuinely-absent heavy-dep name whose ModuleNotFoundError
    signature appears in `combined_output`, or None if no such signature is present."""
    for match in _NO_MODULE_NAMED_RE.findall(combined_output):
        found = _excluded_and_absent(match, excluded)
        if found:
            return found
    return None


def run_pytest_diff(changed_tests: list[str], failed: list[str]) -> None:
    """Orchestrate the --pre pytest-diff step: partition, warn, run once, and reactively fall
    back only on failure (Decision 104 / rec-2485; single-execution reshape).

    Common case: `--collect-only` partitions changed_tests into (runnable, deferred); a loud
    un-swallowable warning is printed per deferred file; the runnable subset is run through pytest
    EXACTLY ONCE. If that run passes (or every file deferred), the gate is done -- no proactive
    per-file isolated probe.

    Only on a non-zero return does this reactively check whether the failure signature names a
    deliberately-excluded, genuinely-absent heavy dependency (a lazy, function-scope import
    invisible to `--collect-only`, e.g. the rec-2572..2576 test_ops_writer.py shape). If so, it
    falls back to per-file classification via `_runtime_heavy_dep_defer_reason` over the runnable
    set, prints DEFERRED warnings for files that resolve to that shape, and re-runs the survivors
    once (reddening only on a survivor failure). Any other failure shape reddens immediately
    (fail-closed) -- no reactive re-run is spent chasing a genuine test failure.
    """
    if not changed_tests:
        return
    runnable, deferred = partition_changed_tests_by_collectability(changed_tests)
    for test_file, missing_dep in deferred:
        _print_deferred_warning(test_file, missing_dep)
    if not runnable:
        print(f"\nAll {len(deferred)} changed test file(s) deferred to the full tier -- fast-tier gate not reddened.")
        return

    print("\n=== Tests (pytest -- explicit changed files) ===")
    cmd = [_common.PYTHON, "-m", "pytest", *runnable, "-m", "not integration", "-v", *_PYTEST_FLAGS]
    result = _common.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT)
    print(result.stdout or "", end="")
    print(result.stderr or "", end="")
    if result.returncode == 0:
        return

    excluded = _excluded_heavy_import_names()
    combined = (result.stdout or "") + (result.stderr or "")
    if _reactive_heavy_dep_signature(combined, excluded) is None:
        # No excluded-heavy-dep signature in the failure output: a genuine failure, a non-heavy
        # collection/runtime error, or an unrelated shape -- redden immediately (fail-closed).
        failed.append("Tests (pytest)")
        return

    survivors: list[str] = []
    for test_file in runnable:
        runtime_missing = _runtime_heavy_dep_defer_reason(test_file, excluded)
        if runtime_missing:
            _print_deferred_warning(test_file, runtime_missing)
        else:
            survivors.append(test_file)
    if not survivors:
        print(
            "\nAll remaining changed test file(s) deferred to the full tier on reactive "
            "detection -- fast-tier gate not reddened."
        )
        return

    print("\n=== Tests (pytest -- reactive re-run on survivors) ===")
    rerun_cmd = [_common.PYTHON, "-m", "pytest", *survivors, "-m", "not integration", "-v", *_PYTEST_FLAGS]
    rerun_result = _common.run(rerun_cmd, cwd=_common.ROOT)
    if rerun_result.returncode != 0:
        failed.append("Tests (pytest)")
