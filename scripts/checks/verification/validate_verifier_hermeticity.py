"""Verifier-hermeticity gate (T3.6, Decision 104)."""

from __future__ import annotations

import ast

from scripts.checks import _common, registry

# Absolute-clock and randomness dotted-name primitives whose use in a HERMETIC verifier fails CI.
# time.perf_counter is ALLOWLISTED (elapsed instrumentation, verdict-independent).
# random.* and secrets.* are gated via _FORBIDDEN_DOTTED_MODULE_PREFIXES (wildcard match).
# 3-level variants cover `import datetime; datetime.datetime.now()` in addition to
# the 2-level `from datetime import datetime; datetime.now()`.
_FORBIDDEN_DOTTED_NAMES: frozenset[str] = frozenset(
    {
        # absolute clock -- 2-level (e.g. from datetime import datetime; datetime.now())
        "time.time",
        "time.time_ns",
        "time.monotonic",
        "time.monotonic_ns",
        "datetime.now",
        "datetime.utcnow",
        "datetime.today",
        "date.today",
        # absolute clock -- 3-level (e.g. import datetime; datetime.datetime.now())
        "datetime.datetime.now",
        "datetime.datetime.utcnow",
        "datetime.datetime.today",
        "datetime.date.today",
        # randomness -- 2-level
        "uuid.uuid1",
        "uuid.uuid3",
        "uuid.uuid4",
        "uuid.uuid5",
        "os.urandom",
    }
)

# Module-name prefixes: any attribute access on these modules is forbidden in HERMETIC verifiers.
_FORBIDDEN_DOTTED_MODULE_PREFIXES: frozenset[str] = frozenset({"random", "secrets"})

# Network-import module names; any import of these or their submodules is forbidden.
_FORBIDDEN_NETWORK_IMPORTS: frozenset[str] = frozenset(
    {
        "boto3",
        "awswrangler",
        "requests",
        "httpx",
        "urllib.request",
        "urllib3",
        "socket",
        "http.client",
    }
)


def _dotted_name_from_attr(node: ast.Attribute) -> str | None:
    """Extract a dotted name of up to 3 levels from an ast.Attribute node.

    Handles both 2-level (`time.time`, root is Name) and 3-level
    (`datetime.datetime.now`, root is Name -> Attribute -> Attribute) chains.
    Returns None when the root is not a simple Name (deeper or dynamic access).
    """
    attr = node.attr
    value = node.value
    if isinstance(value, ast.Name):
        return f"{value.id}.{attr}"
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
        return f"{value.value.id}.{value.attr}.{attr}"
    return None


def _verifier_is_non_hermetic(class_node: ast.ClassDef) -> bool:
    """Return True if the class body explicitly declares NON_HERMETIC_BY_CONSTRUCTION.

    Handles both plain assignment (hermeticity = ...) and type-annotated assignment
    (hermeticity: Hermeticity = ...).
    """
    for stmt in class_node.body:
        # Plain assignment: hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "hermeticity"
            and isinstance(stmt.value, ast.Attribute)
            and stmt.value.attr == "NON_HERMETIC_BY_CONSTRUCTION"
        ):
            return True
        # Type-annotated assignment: hermeticity: Hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION
        if (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.target.id == "hermeticity"
            and stmt.value is not None
            and isinstance(stmt.value, ast.Attribute)
            and stmt.value.attr == "NON_HERMETIC_BY_CONSTRUCTION"
        ):
            return True
    return False


@registry.register("validate_verifier_hermeticity", owner="platform")
def validate_verifier_hermeticity(failed: list[str]) -> None:
    """Fail CI when a HERMETIC-declared (or default) verifier uses a non-hermetic primitive.

    Pure-AST scan (no imports) of scripts/verifiers/*.py. A file is EXEMPT when all of its
    class bodies declare hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION.  Forbidden
    primitives: absolute clock (time.time/time_ns/monotonic/monotonic_ns, datetime.now/utcnow/today,
    date.today), randomness (random.*, uuid.uuid1/3/4/5, secrets.*, os.urandom), and network
    imports (boto3, awswrangler, requests, httpx, urllib.request, urllib3, socket, http.client).
    time.perf_counter is ALLOWLISTED.  Files with SyntaxError are skipped (fail-open per file).
    """
    print("\n=== Verifier hermeticity (T3.6) ===")
    scan_dir = _common.ROOT / "scripts" / "verifiers"
    if not scan_dir.is_dir():
        failed.append("verifier-hermeticity: scripts/verifiers/ not found")
        return

    for py_file in sorted(scan_dir.glob("*.py")):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        if classes and all(_verifier_is_non_hermetic(cls) for cls in classes):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                dotted = _dotted_name_from_attr(node)
                if dotted is None:
                    continue
                root = dotted.split(".")[0]
                if dotted in _FORBIDDEN_DOTTED_NAMES:
                    failed.append(f"verifier-hermeticity: {py_file.name}:{node.lineno}: {dotted}")
                elif root in _FORBIDDEN_DOTTED_MODULE_PREFIXES:
                    failed.append(f"verifier-hermeticity: {py_file.name}:{node.lineno}: {dotted}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name == f or alias.name.startswith(f + ".") for f in _FORBIDDEN_NETWORK_IMPORTS):
                        failed.append(f"verifier-hermeticity: {py_file.name}:{node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(module == f or module.startswith(f + ".") for f in _FORBIDDEN_NETWORK_IMPORTS):
                    failed.append(f"verifier-hermeticity: {py_file.name}:{node.lineno}: from {module} import ...")
