"""Flags cross-test-module imports (Decision 131, enables the rec-2709 mirror convention).

Root cause: once tests/ decomposes package-by-package (mirror convention), each mirror
package must be self-contained -- a test module importing helpers from ANOTHER test_*
module couples two packages together and defeats the point of splitting them. Shared
helpers belong in conftest.py fixtures or tests/fixtures/ (an importable package), neither
of which starts with "test_" so both are exempt by construction.

Detects any ast.Import / ast.ImportFrom in tests/**/*.py whose target module's final
dotted component (or, for a `from . import X` relative import with no module component,
the imported name X itself) starts with "test_". A documented
_GRANDFATHERED_CROSS_TEST_IMPORTS allowlist exempts the one pre-existing violation found
at foundation time (tests/test_verifier_harness.py, a re-export shim of
tests/test_verifiers/test_harness.py) until a later wave removes the shim.
"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.checks import _common, registry

# The one pre-existing cross-test import at foundation time (Decision 131): a documented
# re-export shim ("Redirects to tests/test_verifiers/test_harness.py for package
# consistency"). Retire this entry when a later wave removes the shim by moving the shared
# harness code to tests/fixtures/ or normalizing tests/test_verifiers/ into the mirror tree.
_GRANDFATHERED_CROSS_TEST_IMPORTS: frozenset[str] = frozenset(
    {
        "tests/test_verifier_harness.py",
    }
)


def _imported_names_from_import(node: ast.Import) -> list[str]:
    """Final dotted component of each `import a.b.test_x` alias target."""
    return [alias.name.split(".")[-1] for alias in node.names]


def _imported_names_from_import_from(node: ast.ImportFrom) -> list[str]:
    """Names to check for an `ast.ImportFrom` node.

    `from pkg.mod import X` -> the target module's final component (`mod`).
    `from . import X` (a relative import with no module component) -> each imported name
    X itself, since there is no module component to inspect.
    """
    if node.module is None:
        return [alias.name for alias in node.names]
    return [node.module.split(".")[-1]]


def _scan_file(path: Path) -> list[str]:
    rel = path.relative_to(_common.ROOT).as_posix()
    if rel in _GRANDFATHERED_CROSS_TEST_IMPORTS:
        return []

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = _imported_names_from_import(node)
        elif isinstance(node, ast.ImportFrom):
            names = _imported_names_from_import_from(node)
        else:
            continue
        for name in names:
            if name.startswith("test_"):
                violations.append(f"{rel}:{node.lineno}: imports from another test module ({name})")
    return violations


def _find_violations(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        violations.extend(_scan_file(path))
    return violations


@registry.register("validate_no_cross_test_imports", owner="platform")
def validate_no_cross_test_imports(failed: list[str]) -> None:
    """Fail when a tests/**/*.py module imports from another test module.

    conftest.py and tests/fixtures/** are exempt by construction (their module names
    never start with test_) -- see tests/CLAUDE.md "No cross-test imports".
    """
    print("\n=== No-cross-test-import guard ===")
    tests_dir = _common.ROOT / "tests"
    paths = sorted(tests_dir.glob("**/*.py"))
    violations = _find_violations(paths)
    if violations:
        print("Cross-test-module imports found:")
        for v in violations:
            print(f"  - {v}")
        failed.append("No-cross-test-import guard")
    else:
        print("No cross-test-module imports found.")
