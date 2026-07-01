"""Verifier same-PR guard (T3.1, Decision 104)."""

from __future__ import annotations

import ast

from scripts.checks import _common, registry


def _extract_verifier_covers(class_node: ast.ClassDef) -> list[str] | None:
    """Extract the covers list from a Verifier class body via AST.

    Returns the list of glob strings if a ``covers`` class attribute is found,
    or None if the class inherits the default (["**"]).  Handles both plain
    assignment and annotated assignment; list literals only (dynamic covers not
    supported by the static scanner).
    """
    for stmt in class_node.body:
        target_name: str | None = None
        value_node: ast.expr | None = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target_name = stmt.targets[0].id
            value_node = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target_name = stmt.target.id
            value_node = stmt.value
        if target_name == "covers" and value_node is not None and isinstance(value_node, ast.List):
            return [elt.s for elt in value_node.elts if isinstance(elt, ast.Constant) and isinstance(elt.s, str)]
    return None


@registry.register("validate_verifier_same_pr_guard", owner="platform")
def validate_verifier_same_pr_guard(failed: list[str]) -> None:
    """Reject a PR that touches a verifier file AND any file it covers (--pre, T3.1).

    Exceptions (per CD.29):
      (b) The verifier file is itself new in this diff (first commit cannot violate).
      (c) No covered file appears in the diff (the author is changing only the verifier,
          not any guarded target).

    AST-scan scripts/verifiers/*.py to extract the ``covers`` class attribute.
    Classes without an explicit ``covers`` default to ["**"] (matches everything).
    """
    print("\n=== Verifier same-PR guard (T3.1) ===")
    verifiers_dir = _common.ROOT / "scripts" / "verifiers"
    if not verifiers_dir.is_dir():
        print("  scripts/verifiers/ not found -- skip.")
        return

    changed = _common.get_changed_files()
    changed_set = set(changed)

    git_new = _common.run(
        ["git", "diff", "--name-only", "--diff-filter=A", "origin/main"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    new_files: set[str] = set(git_new.stdout.strip().splitlines()) if git_new.returncode == 0 else set()

    violations: list[str] = []
    for py_file in sorted(verifiers_dir.glob("*.py")):
        rel = str(py_file.relative_to(_common.ROOT))
        if rel not in changed_set:
            continue
        if rel in new_files:
            # Exception (b): verifier is brand-new this PR -- no guard violation possible.
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        if not classes:
            continue

        for cls in classes:
            covers = _extract_verifier_covers(cls) or ["**"]
            import fnmatch as _fnmatch  # noqa: PLC0415

            covered_in_diff = [f for f in changed if f != rel and any(_fnmatch.fnmatch(f, g) for g in covers)]
            if not covered_in_diff:
                # Exception (c): no covered file in this diff.
                continue
            violations.append(
                f"same-pr-guard: {rel} (class {cls.name}) modified in same PR as covered file(s): "
                + ", ".join(covered_in_diff[:3])
                + (" ..." if len(covered_in_diff) > 3 else "")
            )

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
        failed.append("Verifier same-PR guard")
    else:
        print("  OK: no same-PR violations found.")
