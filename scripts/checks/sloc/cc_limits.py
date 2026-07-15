"""Whole-repo cyclomatic-complexity limit check (Decision 43/130)."""

from __future__ import annotations

import ast

from scripts.checks import _common, registry
from scripts.checks.sloc._shared import _BRANCH_TYPES, _CC_LIMIT, _WAIVER_PATTERN, iter_gated_py_files


@registry.register("validate_cc_limits", owner="platform")
def validate_cc_limits(failed: list[str]) -> None:
    """Enforce Decision 43/130: max 20 cyclomatic-complexity branches per function unless waivered."""
    print("\n=== Cyclomatic complexity limits (Decision 43) ===")
    errors: list[str] = []

    for py_file in iter_gated_py_files():
        content = py_file.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        header = "\n".join(lines[:10])
        if _WAIVER_PATTERN.search(header):
            continue
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        rel = str(py_file.relative_to(_common.ROOT)).replace(chr(92), "/")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            branch_count = sum(1 for sub in ast.walk(node) if isinstance(sub, _BRANCH_TYPES))
            if branch_count > _CC_LIMIT:
                errors.append(
                    f"{rel}::{node.name}: {branch_count} branches "
                    f"(limit {_CC_LIMIT}). Add '# complexity-waiver: decision-43' or reduce."
                )

    if errors:
        print("Cyclomatic complexity violations:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Cyclomatic complexity limits (Decision 43)")
    else:
        print("All functions within CC limits or waivered.")
