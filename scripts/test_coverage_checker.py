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

# The four ducklake_runtime split-out modules (PLAN-sloc-ducklake-layer) route to the
# pre-decomposition monolith's test file, mirroring the Decision 104 scripts/checks/** precedent:
# they are the write/table-DDL/read/metrics behavior oracle, exercised via the facade re-export.
_DUCKLAKE_RUNTIME_SPLIT_MODULES = {
    "ducklake_writes.py",
    "ducklake_tables.py",
    "ducklake_reads.py",
    "ducklake_metrics.py",
}


def map_source_to_test(source_path: Path) -> Path | None:
    """Map a source file path to its expected test file path.

    src/**/*.py           -> tests/test_{module}.py  (e.g. src/common/config.py -> tests/test_config.py)
    scripts/*.py          -> tests/test_{name}.py     (e.g. scripts/validate.py -> tests/test_validate.py)
    scripts/checks/**/*.py -> tests/test_validate.py  (every extracted check's tests live there,
                              colocated with the pre-decomposition monolith's test file -- Decision 104),
                              except registry.py/_common.py which map to tests/test_checks_registry.py.
    src/common/ducklake_{writes,tables,reads,metrics}.py -> tests/test_ducklake_runtime.py (split-out
                              from ducklake_runtime.py, PLAN-sloc-ducklake-layer, same Decision 104 precedent).
    src/lambdas/ducklake_writer/<non-handler>.py -> tests/test_ducklake_writer_handler.py (e.g.
                              smoke_actions.py, split-out from handler.py, same precedent).
    scripts/ci_rca/<name>.py -> tests/test_ci_rca_<name>.py (nested subpackage, RS-01 / rec-164 Phase A;
                              the 7 modules moved from scripts/ci_rca_<name>.py keep their flat tests).

    Returns None for paths not under src/ or scripts/.
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
    elif (
        parts[0] == "src"
        and len(parts) >= 4
        and parts[1] == "lambdas"
        and parts[2] == "ducklake_writer"
        and rel.stem != "handler"
    ):
        return ROOT / "tests" / "test_ducklake_writer_handler.py"
    elif parts[0] == "src" and len(parts) >= 2:
        stem = rel.stem
        return ROOT / "tests" / f"test_{stem}.py"
    elif parts[0] == "scripts" and len(parts) >= 2 and parts[1] == "checks":
        if len(parts) >= 3 and parts[2] in _CHECKS_REGISTRY_MECHANISM_FILES:
            return ROOT / "tests" / "test_checks_registry.py"
        return ROOT / "tests" / "test_validate.py"
    elif parts[0] == "scripts" and len(parts) == 3 and parts[1] == "ci_rca":
        # Nested ci_rca subpackage (RS-01 / rec-164 Phase A): the 7 modules moved from
        # scripts/ci_rca_<name>.py keep their flat tests at tests/test_ci_rca_<name>.py.
        stem = rel.stem
        return ROOT / "tests" / f"test_ci_rca_{stem}.py"
    elif parts[0] == "scripts" and len(parts) == 2:
        stem = rel.stem
        return ROOT / "tests" / f"test_{stem}.py"

    return None


def check_test_file_exists(source_path: Path) -> tuple[bool, str]:
    """Check whether a test file exists for the given source file.

    Returns (True, reason) if the test file exists or the path is unmapped.
    Returns (False, reason) if the test file is missing.
    """
    expected = map_source_to_test(source_path)
    if expected is None:
        return True, "skipped: not in src/ or scripts/"
    if expected.exists():
        return True, "test file found"
    try:
        display = expected.relative_to(ROOT)
    except ValueError:
        display = expected
    return False, f"missing test file: {display}"


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
                from scripts.llm_utils import kill_process_tree

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
