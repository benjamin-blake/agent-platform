"""Flags hardcoded exact-count assertions against growing production collections (Decision 104).

Root cause: config/agent/data_quality/source_registry.yaml grows by addition, but
tests/test_rec_write_guidance.py hardcoded `assert len(entries) == 35`. When a 36th
entry was added the assertion broke on the full post-merge tier (the --pre tier's
diff-aware pytest selection never ran the test, since only the YAML changed).

Detects `assert len(X) == N` / `assert N == len(X)` (either comparison order) where
X is curated-linked: a direct reference to a curated collection token, a call to a
curated loader, a string-subscript key into a curated field, or a local name tainted
by assignment from any of the above earlier in the same scope. A `# count-coupling-ok:
<reason>` comment on the assert's line(s) waives a deliberately-sized fixture.
"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.checks import _common, registry

# Growth-prone production collections/loaders this guard defends. Collocated with the
# enforcement logic (AGENTS.md): add a token here when a new curated collection is
# introduced, rather than maintaining a separate allowlist doc.
_CURATED_TOKENS = {
    "load_source_registry",
    "registered_values",
    "TABLE_NAMES",
    "TELEMETRY_TABLE_NAMES",
    "_OPS_TABLE_NAMES",
    "_TELEMETRY_TABLE_NAMES",
}

_WAIVER_MARKER = "# count-coupling-ok:"


def _name_or_attr_is_curated(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _CURATED_TOKENS
    if isinstance(node, ast.Attribute):
        return node.attr in _CURATED_TOKENS
    return False


def _expr_is_curated_linked(node: ast.AST, tainted: set[str]) -> bool:
    """True if `node` (a length-argument expression) touches a curated collection."""
    for sub in ast.walk(node):
        if _name_or_attr_is_curated(sub):
            return True
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id in _CURATED_TOKENS:
                return True
            if isinstance(func, ast.Attribute) and func.attr in _CURATED_TOKENS:
                return True
        if isinstance(sub, ast.Subscript):
            key = sub.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in _CURATED_TOKENS:
                return True
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
    return False


def _iter_scope_nodes(stmts: list[ast.stmt]):
    """Yield every node reachable from `stmts` without descending into a nested
    function/class body -- those are separate scopes, walked independently."""
    stack: list[ast.AST] = list(stmts)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue  # nested scope -- its body is walked independently, not from here
        stack.extend(ast.iter_child_nodes(node))


def _collect_tainted_names(stmts: list[ast.stmt]) -> set[str]:
    """Names in this scope assigned (anywhere in the scope) from a curated-linked RHS."""
    tainted: set[str] = set()
    for node in _iter_scope_nodes(stmts):
        if isinstance(node, ast.Assign) and _expr_is_curated_linked(node.value, set()):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    tainted.add(target.id)
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and _expr_is_curated_linked(node.value, set())
            and isinstance(node.target, ast.Name)
        ):
            tainted.add(node.target.id)
    return tainted


def _len_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len" and len(node.args) == 1:
        return node
    return None


def _extract_len_eq_int(compare: ast.Compare) -> ast.AST | None:
    """Return the length-argument expression if `compare` is `len(X) == N` or `N == len(X)`."""
    if len(compare.ops) != 1 or not isinstance(compare.ops[0], ast.Eq):
        return None
    left, right = compare.left, compare.comparators[0]
    left_len = _len_call(left)
    if left_len is not None and isinstance(right, ast.Constant) and isinstance(right.value, int):
        return left_len.args[0]
    right_len = _len_call(right)
    if right_len is not None and isinstance(left, ast.Constant) and isinstance(left.value, int):
        return right_len.args[0]
    return None


def _assert_has_waiver(lines: list[str], node: ast.Assert) -> bool:
    start = node.lineno
    end = getattr(node, "end_lineno", start) or start
    return any(_WAIVER_MARKER in lines[lineno - 1] for lineno in range(start, end + 1) if 1 <= lineno <= len(lines))


def _scan_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    scopes: list[list[ast.stmt]] = [tree.body]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append(node.body)

    rel = path.relative_to(_common.ROOT)
    violations: list[str] = []
    for scope_body in scopes:
        tainted = _collect_tainted_names(scope_body)
        for node in _iter_scope_nodes(scope_body):
            if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
                continue
            length_expr = _extract_len_eq_int(node.test)
            if length_expr is None:
                continue
            if _expr_is_curated_linked(length_expr, tainted) and not _assert_has_waiver(lines, node):
                violations.append(f"{rel}:{node.lineno}: hardcoded exact-count assertion against a curated collection")
    return violations


def _find_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        violations.extend(_scan_file(path))
    return violations


@registry.register("validate_test_count_coupling", owner="platform")
def validate_test_count_coupling(failed: list[str]) -> None:
    """Scan tests/ for hardcoded exact-count assertions against curated growth-prone collections."""
    print("\n=== Test-count coupling guard ===")
    tests_dir = _common.ROOT / "tests"
    paths = sorted(tests_dir.glob("**/*.py"))
    violations = _find_violations(paths)
    if violations:
        print("Hardcoded exact-count assertions found:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Test-count coupling guard")
    else:
        print("No hardcoded exact-count assertions against curated collections found.")
