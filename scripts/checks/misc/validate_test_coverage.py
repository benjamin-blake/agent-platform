from __future__ import annotations

import importlib.util
import sys

from scripts.checks import _common, registry


def _load_coverage_checker():
    """Lazy-load test_coverage_checker to avoid import-time subprocess calls."""
    checker_path = _common.ROOT / "scripts" / "test_coverage_checker.py"
    if not checker_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("test_coverage_checker", checker_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    # Ensure repo root is in sys.path so intra-package imports resolve
    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    return mod


@registry.register("validate_test_coverage", owner="platform")
def validate_test_coverage(failed: list[str]) -> None:
    """Check that changed source files have test files and 100% per-file coverage."""
    print("\n=== Test coverage check ===")

    # Break recursion: if we're already inside a coverage subprocess
    # (test_coverage_checker.py -> pytest -> test -> validate.py), skip
    # the coverage check to prevent infinite fork explosion.
    import os

    if os.environ.get("_COVERAGE_SUBPROCESS") == "1":
        print("Inside coverage subprocess — skipping to prevent recursion.")
        return

    checker = _load_coverage_checker()
    if checker is None:
        print("test_coverage_checker.py not found — skipping.")
        return

    source_files = checker.get_changed_source_files()
    if not source_files:
        print("No source file changes to check.")
        return

    missing_tests: list[str] = []
    for src in source_files:
        ok, msg = checker.check_test_file_exists(src)
        if not ok:
            try:
                rel = src.relative_to(_common.ROOT)
            except ValueError:
                rel = src
            missing_tests.append(f"{rel}: {msg}")

    coverage_errors: list[str] = []
    if not missing_tests:
        coverage_errors = checker.check_per_file_coverage(source_files)

    n = len(source_files)
    m = len(missing_tests)
    k = len(coverage_errors)
    print(f"Test coverage check: {n} source files checked, {m} missing test files, {k} below 100% coverage")

    if missing_tests:
        for e in missing_tests:
            print(f"  - {e}")
        failed.append("Test coverage check")

    if coverage_errors:
        for e in coverage_errors:
            print(f"  - {e}")
        failed.append("Coverage below 100%")
