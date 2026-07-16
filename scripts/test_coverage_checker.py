#!/usr/bin/env python3
"""AST-based test coverage checker.

For each changed Python source file, verifies:
1. A corresponding test file exists.
2. Per-file line coverage is 100% (when --check-coverage is set).

Usage:
    python scripts/test_coverage_checker.py --check-tests
    python scripts/test_coverage_checker.py --check-coverage
    python scripts/test_coverage_checker.py --check-tests --check-coverage
    python scripts/test_coverage_checker.py --check-tests --files src/common/config.py
"""

import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def extract_definitions(file_path: Path) -> list[str]:
    """Extract public function, async function, and class names at module level.

    Skips private definitions (names starting with '_').
    """
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, OSError):
        return []

    names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    return names


# scripts/checks/registry.py and _common.py are the check-registry mechanism itself
# (Decision 104); they're exercised directly by tests/test_checks_registry.py (frozen
# baseline, facade completeness, mock-interception, owner metadata), not by any
# individual check's tests in tests/test_validate.py.
_CHECKS_REGISTRY_MECHANISM_FILES = {"_common.py", "registry.py"}

# scripts/checks/_scaffolding.py and _terraform.py are orchestration-internal helper modules --
# not themselves registered checks -- whose tests have always lived alongside the orchestrator's
# own tests (never with the per-check mirrors). Once "test_validate.py" retires from
# _RETIRING_GRANDFATHER_HOMES (rec-2709 Wave 1), they route to the SAME tests/validate/
# concern-split package scripts/validate.py itself resolves to (see the
# "scripts/validate.py" entry in _CONCERN_SPLIT_TEST_PACKAGES below), rather than falling
# through to the generic drop-root mirror rule (which would otherwise compute
# tests/checks/test__scaffolding.py -- wrong; their real home is the orchestrator package).
_ORCHESTRATION_SCAFFOLDING_FILES = {"_scaffolding.py", "_terraform.py"}

# The four ducklake_runtime split-out modules (PLAN-sloc-ducklake-layer) route to the
# pre-decomposition monolith's test file, mirroring the Decision 104 scripts/checks/** precedent:
# they are the write/table-DDL/read/metrics behavior oracle, exercised via the facade re-export.
_DUCKLAKE_RUNTIME_SPLIT_MODULES = {
    "ducklake_writes.py",
    "ducklake_tables.py",
    "ducklake_reads.py",
    "ducklake_metrics.py",
}

# Nested scripts/ subpackages (RS-01 / rec-164): each len==3 module maps to a kept-in-place flat
# test file. session_*/sync_* strip the family prefix (module stem alone re-prefixed here);
# roadmap keeps full names (empty-suffix -> test_<stem>); llm is mixed (client/utils strip the
# llm_ prefix, model_registry/github_models_client keep their names) but a single "test_llm_"
# prefix reproduces all four via the two renamed tests (test_llm_model_registry.py,
# test_llm_github_models_client.py). Whitelisted to the five known subpackages so a NEW
# scripts/<pkg>/ does not silently inherit a mapping (do not generalise to any len==3).
_NESTED_SUBPACKAGE_TEST_PREFIX = {
    "ci_rca": "test_ci_rca_",
    "session": "test_session_",
    "sync": "test_sync_",
    "roadmap": "test_",
    "llm": "test_llm_",
}


def _grandfathered_source_to_test(source_path: Path) -> Path | None:
    """Pre-inversion (Decision 104 colocation) mapping -- verbatim body, preserved as the
    grandfather oracle every _RETIRING_GRANDFATHER_HOMES entry still resolves through.

    src/**/*.py           -> tests/test_{module}.py  (e.g. src/common/config.py -> tests/test_config.py)
    scripts/*.py          -> tests/test_{name}.py     (e.g. scripts/validate.py -> tests/test_validate.py)
    scripts/checks/**/*.py -> tests/test_validate.py  (every extracted check's tests live there,
                              colocated with the pre-decomposition monolith's test file -- Decision 104),
                              except registry.py/_common.py which map to tests/test_checks_registry.py.
    scripts/convergence_health/*.py -> tests/test_convergence_health.py (facade decomposition of
                              the former single-file convergence_health monolith, same Decision 104
                              colocation precedent -- PLAN-convergence-health-sloc-decompose-guardrails).
    src/common/ducklake_{writes,tables,reads,metrics}.py -> tests/test_ducklake_runtime.py (split-out
                              from ducklake_runtime.py, PLAN-sloc-ducklake-layer, same Decision 104 precedent).
    src/lambdas/<slug>/*.py -> tests/test_{slug}_handler.py (parent-qualified rule, RS-08): every
                              file under a src/lambdas/<slug>/ directory -- handler.py plus any
                              split-out sibling (e.g. ducklake_writer/smoke_actions.py) -- maps to
                              that lambda's single test home, keyed off the parent slug rather than
                              the file's own stem. Generalizes the former ducklake_writer-only
                              special case so every src/lambdas/*/handler.py resolves to its own
                              distinct, real test home instead of colliding on the stem-based
                              tests/test_handler.py fallback (retired).
    scripts/{ci_rca,session,sync,roadmap,llm}/<name>.py -> the module's kept-in-place flat test
                              (nested subpackages, RS-01 / rec-164): ci_rca/session/sync strip the
                              family prefix -> test_ci_rca_/test_session_/test_sync_<name>.py; roadmap
                              keeps full names -> test_<name>.py; llm is mixed (client/utils strip the
                              llm_ prefix, model_registry/github_models_client keep their names) but
                              all four resolve via the single test_llm_ prefix -> test_llm_client.py,
                              test_llm_utils.py, test_llm_model_registry.py,
                              test_llm_github_models_client.py. See _NESTED_SUBPACKAGE_TEST_PREFIX
                              (whitelisted to these five; no general len==3 rule).

    Returns None for paths not under src/ or scripts/ -- including scripts/executor/** and
    scripts/ops_portal/**, which deliberately have no source-to-test mapping (Decision 124).
    """
    try:
        rel = source_path.resolve().relative_to(ROOT)
    except ValueError:
        return None

    parts = rel.parts
    if not parts:
        return None

    if parts[0] == "src" and len(parts) >= 3 and parts[1] == "common" and rel.name in _DUCKLAKE_RUNTIME_SPLIT_MODULES:
        return ROOT / "tests" / "test_ducklake_runtime.py"
    elif parts[0] == "src" and len(parts) >= 4 and parts[1] == "lambdas":
        return ROOT / "tests" / f"test_{parts[2]}_handler.py"
    elif parts[0] == "src" and len(parts) >= 2:
        stem = rel.stem
        return ROOT / "tests" / f"test_{stem}.py"
    elif parts[0] == "scripts" and len(parts) >= 2 and parts[1] == "checks":
        if len(parts) >= 3 and parts[2] in _CHECKS_REGISTRY_MECHANISM_FILES:
            return ROOT / "tests" / "test_checks_registry.py"
        return ROOT / "tests" / "test_validate.py"
    elif parts[0] == "scripts" and len(parts) == 3 and parts[1] == "convergence_health":
        return ROOT / "tests" / "test_convergence_health.py"
    elif parts[0] == "scripts" and len(parts) == 3 and parts[1] in _NESTED_SUBPACKAGE_TEST_PREFIX:
        # Nested scripts/ subpackages (RS-01 / rec-164): ci_rca/session/sync strip the family
        # prefix, roadmap keeps full names -- each module keeps its flat test (see the prefix map).
        # One dict-lookup branch (not four parallel elifs) keeps this function under the
        # Decision 43 cyclomatic-complexity ceiling; still whitelisted (no general len==3 rule).
        return ROOT / "tests" / f"{_NESTED_SUBPACKAGE_TEST_PREFIX[parts[1]]}{rel.stem}.py"
    elif parts[0] == "scripts" and len(parts) == 2:
        stem = rel.stem
        return ROOT / "tests" / f"test_{stem}.py"

    return None


# The fixed rec-2709 roster: the 24 tests/ basenames grandfathered whole-repo by Decision 130
# (config/sloc_budgets.yaml). A frozenset -- membership only, never mutated.
_ALL_MIRROR_TARGET_HOMES: frozenset[str] = frozenset(
    {
        "test_build_lambda_deploy.py",
        "test_ci_rca_evidence.py",
        "test_contracts_enforcement.py",
        "test_convergence_health.py",
        "test_ducklake_maintenance_handler.py",
        "test_ducklake_neon_smoke_test.py",
        "test_ducklake_runtime.py",
        "test_ducklake_writer_handler.py",
        "test_execute_recommendation.py",
        "test_executor_plan.py",
        "test_executor_postflight.py",
        "test_executor_step_runner.py",
        "test_iceberg_reader.py",
        "test_lambda_manifest.py",
        "test_ops_data_portal.py",
        "test_ops_writer.py",
        "test_platform_roadmap_state.py",
        "test_s3_log_store.py",
        "test_scheduled_agent_handler.py",
        "test_session_postflight.py",
        "test_session_preflight.py",
        "test_sync_ops.py",
        "test_validate.py",
        "test_verify_ci_workflow.py",
    }
)

# The not-yet-decomposed subset of _ALL_MIRROR_TARGET_HOMES -- a home in this set still
# resolves through the grandfather (colocation) rule; a wave RETIRES a target by deleting
# its one line here, which switches every source path mapping to that home over to the
# mirror rule. Seeded == _ALL_MIRROR_TARGET_HOMES on day one, so the mirror branch below is
# dormant and map_source_to_test is byte-identical to the pre-inversion function for every
# input (proven by TestMapSourceToTest / TestCheckTestFileExists staying green unchanged).
# Kept a plain set literal, one basename per line, for minimal per-wave merge conflict.
_RETIRING_GRANDFATHER_HOMES: set[str] = {
    "test_build_lambda_deploy.py",
    "test_ci_rca_evidence.py",
    "test_contracts_enforcement.py",
    "test_convergence_health.py",
    "test_ducklake_maintenance_handler.py",
    "test_ducklake_neon_smoke_test.py",
    "test_ducklake_runtime.py",
    "test_ducklake_writer_handler.py",
    "test_execute_recommendation.py",
    "test_executor_plan.py",
    "test_executor_postflight.py",
    "test_executor_step_runner.py",
    "test_iceberg_reader.py",
    "test_lambda_manifest.py",
    "test_ops_data_portal.py",
    "test_ops_writer.py",
    "test_platform_roadmap_state.py",
    "test_s3_log_store.py",
    "test_scheduled_agent_handler.py",
    "test_session_postflight.py",
    "test_session_preflight.py",
    "test_sync_ops.py",
    "test_verify_ci_workflow.py",
}

# Repo-relative (POSIX, ROOT-relative) source paths whose mirror target is a test PACKAGE
# DIRECTORY rather than a single test_<stem>.py file: single-file monoliths with no
# per-submodule source to mirror 1:1, so their eventual decomposition splits the TEST by
# concern into multiple test_*.py modules under one directory. Entries are dormant until
# their _RETIRING_GRANDFATHER_HOMES line is deleted; each wave finalises its own membership
# (this seed is the known monolith roster at foundation time, not a closed list).
_CONCERN_SPLIT_TEST_PACKAGES: frozenset[str] = frozenset(
    {
        "scripts/ops_writer.py",
        "scripts/ops_data_portal.py",
        "scripts/s3_log_store.py",
        "scripts/verify_ci_workflow.py",
        "scripts/contracts_enforcement.py",
        "scripts/platform_roadmap_state.py",
        "scripts/build_lambda_deploy.py",
        "scripts/lambda_manifest.py",
        "scripts/ducklake_neon_smoke_test.py",
        "src/common/iceberg_reader.py",
        "src/data/handlers/scheduled_agent_handler.py",
        "scripts/checks/iam_tf/validate_ci_refresh_read_coverage.py",
        "scripts/validate.py",
    }
)


def _mirror_source_to_test(source_path: Path) -> Path | None:
    """Mirror-convention target for `source_path`, used once its grandfather home retires.

    Drops the leading src/scripts root segment, keeps the remaining directory sub-path, and
    names the test test_<stem>.py in that mirrored directory -- e.g.
    scripts/checks/hygiene/validate_prose_allowlist.py ->
    tests/checks/hygiene/test_validate_prose_allowlist.py; scripts/executor/step_runner.py ->
    tests/executor/test_step_runner.py; src/common/config.py -> tests/common/test_config.py.
    A root script (no sub-path, e.g. scripts/validate.py) mirrors to tests/test_validate.py --
    identical to the flat rule, so retiring a root-script home is a no-op unless the source is
    a declared concern-split monolith. A declared concern-split monolith
    (_CONCERN_SPLIT_TEST_PACKAGES) instead resolves to its test PACKAGE DIRECTORY (no test_
    prefix, no .py suffix) -- e.g. scripts/ops_writer.py -> tests/ops_writer/;
    src/common/iceberg_reader.py -> tests/common/iceberg_reader/.
    """
    try:
        rel = source_path.resolve().relative_to(ROOT)
    except ValueError:
        return None

    parts = rel.parts
    if len(parts) < 2:
        return None

    mirror_subdir = Path(*parts[1:-1]) if len(parts) > 2 else Path()
    stem = rel.stem

    if rel.as_posix() in _CONCERN_SPLIT_TEST_PACKAGES:
        return ROOT / "tests" / mirror_subdir / stem
    return ROOT / "tests" / mirror_subdir / f"test_{stem}.py"


def map_source_to_test(source_path: Path) -> Path | None:
    """Map a source file path to its expected test file (or test package directory) path.

    Two rules, gated by a retiring grandfather-table (Decision 131, amends Decision 104):

    1. COLOCATION (grandfathered, retiring): while a source path's grandfathered test home's
       basename is still in _RETIRING_GRANDFATHER_HOMES, the pre-inversion colocation rule
       applies unchanged -- see _grandfathered_source_to_test for its full per-pattern table.
    2. MIRROR (post-retirement): once a wave deletes that basename from
       _RETIRING_GRANDFATHER_HOMES, every source path that grandfathers to it instead resolves
       via _mirror_source_to_test -- drop the leading src/scripts root, keep the remaining
       sub-path, name the file test_<stem>.py (or, for a declared concern-split monolith, the
       test PACKAGE DIRECTORY <mirror-subpath>/<stem>/). Examples: scripts/checks/hygiene/
       validate_prose_allowlist.py -> tests/checks/hygiene/test_validate_prose_allowlist.py;
       scripts/executor/step_runner.py -> tests/executor/test_step_runner.py;
       src/common/config.py -> tests/common/test_config.py; scripts/ops_writer.py (concern-split)
       -> tests/ops_writer/.

    WHY drop-root is safe/chosen: it matches established repo precedent (tests/checks/,
    tests/test_verifiers/) and standard pytest tree-mirroring, and is collision-free for the
    fixed 24-home roster because no scripts/<x>/ vs src/<x>/ subdirectory-name overlap exists.
    KNOWN BOUNDARY: a future scripts/<x>/ vs src/<x>/ collision would need a preserve-root
    exception for that pair -- out of scope now, flagged for the map's maintainer.

    scripts/executor/** and scripts/ops_portal/** deliberately return None on both rules
    (Decision 124) -- their grandfathered home is already None, so neither the retiring nor the
    mirror branch ever fires for them; a source path with no grandfathered home never joins the
    roster.

    Day one, _RETIRING_GRANDFATHER_HOMES == _ALL_MIRROR_TARGET_HOMES (every target was still
    retiring), so the mirror branch below was never taken and every result was byte-identical to
    the pre-inversion function (the TestMapSourceToTest / TestCheckTestFileExists oracle proved
    this on day one; see TestGrandfatherRetiringTable for the current, post-Wave-1 state). Each
    wave retires exactly one basename (a one-line, low-merge-conflict edit to
    _RETIRING_GRANDFATHER_HOMES) -- rec-2709 Wave 1 (PLAN-sloc-test-validate) retired
    "test_validate.py", the first of the 24-home roster to flip: every scripts/checks/**/*.py
    (and scripts/validate.py itself) now resolves via the mirror rule instead of colocating in
    the now-deleted tests/test_validate.py.

    scripts/checks/_scaffolding.py and _terraform.py are a special case within the retired
    "test_validate.py" home: they are orchestration-internal helpers, not registered checks, so
    once "test_validate.py" retires they route to the SAME tests/validate/ concern-split package
    scripts/validate.py resolves to (not the generic per-file mirror target) -- see
    _ORCHESTRATION_SCAFFOLDING_FILES.

    Returns None for paths not under src/ or scripts/, or with no grandfathered home.
    """
    home = _grandfathered_source_to_test(source_path)
    if home is None:
        return None
    if home.name in _RETIRING_GRANDFATHER_HOMES:
        return home
    if home.name in _ALL_MIRROR_TARGET_HOMES:
        if home.name == "test_validate.py":
            try:
                rel_name = source_path.resolve().relative_to(ROOT).name
            except ValueError:
                rel_name = source_path.name
            if rel_name in _ORCHESTRATION_SCAFFOLDING_FILES:
                return ROOT / "tests" / "validate"
        return _mirror_source_to_test(source_path)
    return home


def check_test_file_exists(source_path: Path) -> tuple[bool, str]:
    """Check whether a test file (or, for a concern-split target, a test package directory)
    exists for the given source file.

    Returns (True, reason) if the test file/package exists or the path is unmapped.
    Returns (False, reason) if the test file/package is missing.
    """
    expected = map_source_to_test(source_path)
    if expected is None:
        return True, "skipped: not in src/ or scripts/"
    if expected.suffix != ".py":
        # Concern-split mirror target: a test PACKAGE DIRECTORY, not a single file.
        if expected.is_dir() and any(expected.glob("test_*.py")):
            return True, "test package found"
        try:
            display = expected.relative_to(ROOT)
        except ValueError:
            display = expected
        return False, f"missing test package: {display}"
    if expected.exists():
        return True, "test file found"
    try:
        display = expected.relative_to(ROOT)
    except ValueError:
        display = expected
    return False, f"missing test file: {display}"


def _is_empty_directory_target(test_path: Path) -> bool:
    """True if `test_path` is a concern-split test PACKAGE DIRECTORY not yet populated with
    any test_*.py -- factored out so check_per_file_coverage's own branch count (Decision 43)
    absorbs one Call node instead of the nested is_dir()/any() pair."""
    return test_path.is_dir() and not any(test_path.glob("test_*.py"))


def check_per_file_coverage(source_files: list[Path]) -> list[str]:
    """Run pytest coverage for each source file and return files below 100%.

    Returns a list of error strings for files with < 100% line coverage.
    If coverage.py is not available, returns an informational warning (not blocking).
    """
    errors: list[str] = []

    for source_path in source_files:
        try:
            rel = source_path.resolve().relative_to(ROOT)
        except ValueError:
            continue

        # Convert path to module-style for --cov argument
        # e.g. src/common/config.py -> src/common/config
        module_str = str(rel.with_suffix("")).replace("\\", "/")

        # Run only the corresponding test file instead of the full suite.
        # Running `pytest tests/` for each source file triggers a recursive
        # fork explosion: test collection re-invokes validate.py, which
        # re-invokes check_per_file_coverage, each spawning more pytest processes.
        test_path = map_source_to_test(source_path)
        if test_path is None or not test_path.exists():
            continue
        # Concern-split mirror target (post-retirement): run pytest against the whole test
        # package directory (test_path_str below); skip if not yet populated -- mirrors the
        # check_test_file_exists directory guard.
        if _is_empty_directory_target(test_path):
            continue
        test_path_str = str(test_path.relative_to(ROOT)).replace("\\", "/")

        # Set _COVERAGE_SUBPROCESS=1 so any validate.py invoked transitively
        # (e.g. by a test calling subprocess) knows it's inside a coverage run
        # and skips the coverage check, breaking the recursion chain.
        child_env = os.environ.copy()
        child_env["_COVERAGE_SUBPROCESS"] = "1"

        with subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                test_path_str,
                f"--cov={module_str}",
                "--cov-report=json:.coverage.json",
                "-q",
                "--no-header",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
            env=child_env,
        ) as proc:
            try:
                proc.communicate(timeout=300)
            except subprocess.TimeoutExpired:
                # Kill entire process tree to prevent orphan accumulation
                from scripts.llm.utils import kill_process_tree

                kill_process_tree(proc.pid)
                proc.wait()
                errors.append(f"{rel}: coverage check timed out (300s)")
                continue

        coverage_json = ROOT / ".coverage.json"
        if not coverage_json.exists():
            # coverage.py unavailable or file not tracked — informational, not blocking
            print(f"  [info] no coverage data for {rel} (coverage.py unavailable or file not tracked)")
            continue

        try:
            data = json.loads(coverage_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        finally:
            try:
                coverage_json.unlink()
            except OSError:
                pass

        files_data = data.get("files", {})
        matched: dict[str, float] = {}
        rel_str = str(rel).replace("\\", "/")
        for file_key, file_data in files_data.items():
            normalised_key = file_key.replace("\\", "/")
            if rel_str in normalised_key or normalised_key.endswith(rel_str):
                summary = file_data.get("summary", {})
                pct = summary.get("percent_covered", 0.0)
                matched[file_key] = pct

        if not matched:
            # No coverage data means no tests exercised this file
            errors.append(f"{rel}: 0% coverage (no tests exercise this file)")
            continue

        for file_key, pct in matched.items():
            if pct < 100.0:
                errors.append(f"{rel}: {pct:.1f}% line coverage (expected 100%)")

    return errors


def get_changed_source_files(files: list[str] | None = None) -> list[Path]:
    """Return changed Python source files under src/ or scripts/.

    Uses merge-base against origin/main for accurate feature-branch diffs.
    Excludes __init__.py, conftest.py, and test files.

    If files is provided, uses that list instead of git diff.
    """
    if files is not None:
        paths: list[Path] = []
        for f in files:
            p = Path(f)
            if not p.is_absolute():
                p = ROOT / p
            paths.append(p.resolve())
    else:
        # Get merge-base for accurate feature-branch diff
        merge_base_result = subprocess.run(
            ["git", "merge-base", "origin/main", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
        )
        if merge_base_result.returncode != 0:
            # Fallback: diff against HEAD
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
            )
            raw = diff_result.stdout.strip().splitlines()
        else:
            merge_base = merge_base_result.stdout.strip()
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", merge_base],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
            )
            raw = diff_result.stdout.strip().splitlines()

        paths = [ROOT / f for f in raw if f.endswith(".py")]

    result: list[Path] = []
    excluded_names = {"__init__.py", "conftest.py"}
    for p in paths:
        if not p.suffix == ".py":
            continue
        if p.name in excluded_names:
            continue
        # Exclude test files
        if p.name.startswith("test_") or p.name == "conftest.py":
            continue
        try:
            rel = p.resolve().relative_to(ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if parts and parts[0] in ("src", "scripts"):
            if p.resolve().exists():
                result.append(p.resolve())

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check that changed Python source files have test files and 100%% coverage.")
    parser.add_argument(
        "--check-tests",
        action="store_true",
        help="Verify that a test file exists for each changed source file.",
    )
    parser.add_argument(
        "--check-coverage",
        action="store_true",
        help="Verify that per-file line coverage is 100%% for each changed source file.",
    )
    parser.add_argument(
        "--files",
        nargs="+",
        help="Explicit list of source files to check instead of git diff.",
    )
    args = parser.parse_args()

    if not args.check_tests and not args.check_coverage:
        parser.print_help()
        sys.exit(0)

    source_files = get_changed_source_files(args.files)

    if not source_files:
        print("No source file changes to check.")
        sys.exit(0)

    print(f"Checking {len(source_files)} source file(s)...")

    errors: list[str] = []

    if args.check_tests:
        missing_tests: list[str] = []
        for src in source_files:
            ok, msg = check_test_file_exists(src)
            if not ok:
                missing_tests.append(f"  {src.relative_to(ROOT)}: {msg}")
        if missing_tests:
            errors.append("Missing test files:")
            errors.extend(missing_tests)
        else:
            print(f"  Test files: all {len(source_files)} source files have test files.")

    if args.check_coverage:
        coverage_errors = check_per_file_coverage(source_files)
        if coverage_errors:
            errors.append("Coverage failures (< 100%):")
            for e in coverage_errors:
                errors.append(f"  {e}")
        else:
            print(f"  Coverage: all {len(source_files)} source files at 100%.")

    if errors:
        print("\nTest coverage check FAILED:")
        for e in errors:
            print(e)
        sys.exit(1)

    print(f"\nTest coverage check: {len(source_files)} source files checked, 0 missing test files, 0 below 100% coverage")
    sys.exit(0)


if __name__ == "__main__":
    main()
