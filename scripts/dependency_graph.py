# complexity-waiver: decision-43
"""First-party import-graph oracle using ast + networkx (Decision 80).

Compute-on-demand; no committed output file by default.
Stable API: build_graph, roots, reverse_deps, forward_closure,
reachable_from_roots, to_export_dict, check_export_freshness.
CLI: --reverse-deps, --forward-closure, --reachable, --granularity, --export, --blind-spots.
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import networkx as nx

_REPO_ROOT = Path(__file__).parent.parent
_SEARCH_DIRS: tuple[str, ...] = ("src", "scripts", "tests")
_FIRST_PARTY_ROOTS: tuple[str, ...] = ("src", "scripts")
_EXPORT_PATH = _REPO_ROOT / "docs" / "dependency-graph.json"
_CLI_PATTERN = re.compile(r"-m\s+(scripts(?:\.\w+)+)")
# Soundness patch (ii), Decision affected-set-selection: a string literal naming a first-party
# module or module.attribute path (e.g. a mock.patch("scripts.checks._common.run") target).
# Matched against the WHOLE string; the module edge itself resolves to the longest graph-node
# prefix of the match (see _patch_string_module_targets), so both a bare module-path string and
# a module.attribute string resolve to their owning module node.
_PATCH_STRING_RE = re.compile(r"^(src|scripts)(\.\w+)+$")

KNOWN_UNSOUND: list[dict[str, str]] = [
    {
        "pattern": "getattr",
        "description": "Dynamic attribute access; the resolved attribute is invisible to ast-based analysis.",
    },
    {
        "pattern": "string-keyed dispatch",
        "description": "Dict-keyed handler dispatch (e.g. HANDLERS[name]()) cannot be traced statically.",
    },
    {
        "pattern": "importlib.spec_from_file_location",
        "description": "Dynamic module loading via importlib; the target module is invisible to ast.",
    },
    {
        "pattern": "schedule.yaml -> prompt_path -> handler indirection",
        "description": (
            "Scheduled-agent dispatch via .github/agents/schedule.yaml resolves handler modules at runtime; "
            "no static import edge exists between the dispatcher and the scheduled module."
        ),
    },
]


def _file_to_module(py_file: Path, repo_root: Path = _REPO_ROOT) -> str | None:
    """Convert a .py path to a dotted first-party module name, or None if outside search dirs."""
    for search_dir in _SEARCH_DIRS:
        base = repo_root / search_dir
        try:
            rel = py_file.relative_to(base)
        except ValueError:
            continue
        parts = [search_dir] + list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts) if parts else None
    return None


def _has_entry_point(tree: ast.Module) -> bool:
    """True if the module declares if __name__ == '__main__' or def main()."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main":
            return True
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            left = node.test.left
            if isinstance(left, ast.Name) and left.id == "__name__":
                for comp in node.test.comparators:
                    if isinstance(comp, ast.Constant) and comp.value == "__main__":
                        return True
    return False


def _gather_roots(repo_root: Path) -> frozenset[str]:
    """Assemble declared root/boundary module set (Decision 79 -- no transitive resolution).

    Sources: Lambda manifest handlers+includes (all statuses), modules with __main__/main(),
    pytest test files, and -m scripts.X CLI surfaces in .github/workflows + .claude/.
    """
    found: set[str] = set()

    try:
        from scripts.lambda_manifest import load_all  # noqa: PLC0415

        for manifest in load_all().values():
            for path_str in manifest.handlers + manifest.includes:
                p = repo_root / path_str
                if p.is_file() and p.suffix == ".py":
                    mod = _file_to_module(p, repo_root)
                    if mod:
                        found.add(mod)
    except Exception:  # noqa: BLE001
        pass

    for search_dir in ("src", "scripts"):
        sdir = repo_root / search_dir
        if not sdir.is_dir():
            continue
        for py_file in sorted(sdir.rglob("*.py")):
            if py_file.name == "__init__.py":
                continue
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except (OSError, SyntaxError):
                continue
            if _has_entry_point(tree):
                mod = _file_to_module(py_file, repo_root)
                if mod:
                    found.add(mod)

    tests_dir = repo_root / "tests"
    if tests_dir.is_dir():
        for tf in sorted(tests_dir.glob("test_*.py")):
            mod = _file_to_module(tf, repo_root)
            if mod:
                found.add(mod)

    workflows_dir = repo_root / ".github" / "workflows"
    if workflows_dir.is_dir():
        for wf in sorted(workflows_dir.glob("*.yml")):
            try:
                for m in _CLI_PATTERN.finditer(wf.read_text(encoding="utf-8")):
                    found.add(m.group(1))
            except OSError:
                pass

    claude_dir = repo_root / ".claude"
    if claude_dir.is_dir():
        for md in sorted(claude_dir.rglob("*.md")):
            try:
                for m in _CLI_PATTERN.finditer(md.read_text(encoding="utf-8")):
                    found.add(m.group(1))
            except OSError:
                pass

    return frozenset(found)


def _imports_for_file(py_file: Path, repo_root: Path) -> list[str]:
    """Return first-party import names for py_file using scripts.extract_imports."""
    try:
        from scripts.extract_imports import extract_first_party_imports  # noqa: PLC0415

        return extract_first_party_imports(py_file, roots=_FIRST_PARTY_ROOTS, _repo_root=repo_root)
    except ImportError:
        return []


def _enrich_symbol_layer(graph: nx.DiGraph, py_file: Path, module: str) -> None:
    """Add function/class-level symbol nodes and statically-resolvable cross-module call edges."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (OSError, SyntaxError):
        return

    imported_from: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local = alias.asname or alias.name
                imported_from[local] = node.module

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sym = f"{module}.{stmt.name}"
            if sym not in graph:
                graph.add_node(sym, kind="symbol")
            for child in ast.walk(stmt):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
                    src_mod = imported_from.get(child.func.id)
                    if src_mod and src_mod in graph:
                        graph.add_edge(sym, src_mod)
        elif isinstance(stmt, ast.ClassDef):
            sym = f"{module}.{stmt.name}"
            if sym not in graph:
                graph.add_node(sym, kind="symbol")


def _patch_string_module_targets(py_file: Path, graph: nx.DiGraph) -> list[str]:
    """Soundness patch (ii), Decision affected-set-selection: AST pass over ast.Constant string
    literals matching _PATCH_STRING_RE, resolved to the LONGEST existing graph-node module
    prefix of each match.

    Handles both a bare module-path string (e.g. "scripts.checks.deps.affected_tests") and a
    module.attribute mock-patch target (e.g. "scripts.checks._common.run", where only
    "scripts.checks._common" is a real module node) -- the longest-prefix walk resolves either
    shape to its owning module without requiring the caller to know which shape a given string
    is. A candidate that resolves to no known module (e.g. an unrelated dotted string that only
    coincidentally matches the pattern) contributes no edge.
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (OSError, SyntaxError):
        return []
    targets: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        value = node.value
        if not _PATCH_STRING_RE.match(value):
            continue
        parts = value.split(".")
        for end in range(len(parts), 1, -1):
            candidate = ".".join(parts[:end])
            if candidate in graph:
                targets.append(candidate)
                break
    return targets


def build_graph(
    repo_root: Path | None = None,
    granularity: str = "module",
) -> nx.DiGraph:
    """Build and return the first-party import graph.

    Nodes: dotted module names with kind='module'. Edges: A->B means A imports B.
    Root nodes are tagged graph.nodes[mod]['is_root'] = True.
    granularity='symbol' adds function/class nodes (kind='symbol') and call edges.

    Soundness patch (i), Decision affected-set-selection: package __init__.py files ARE
    included as graph nodes (dotted package name, via _file_to_module's existing __init__
    stripping) so a facade re-export (Decision 124: `__init__.py` re-exporting a submodule's
    public surface) does not silently drop the edge from an importer of the package to the
    package node itself -- previously __init__.py was skipped entirely, so
    `from scripts.checks.deps import X` (importing the PACKAGE) had no node to land on and the
    edge was dropped.
    """
    root = repo_root if repo_root is not None else _REPO_ROOT
    graph: nx.DiGraph = nx.DiGraph()

    py_files: list[tuple[Path, str]] = []
    for search_dir in _SEARCH_DIRS:
        sdir = root / search_dir
        if not sdir.is_dir():
            continue
        for py_file in sorted(sdir.rglob("*.py")):
            mod = _file_to_module(py_file, root)
            if mod:
                graph.add_node(mod, kind="module")
                py_files.append((py_file, mod))

    for py_file, mod in py_files:
        for imported_mod in _imports_for_file(py_file, root):
            if imported_mod in graph and imported_mod != mod:
                graph.add_edge(mod, imported_mod)
        # Soundness patch (ii): union string-constant module edges (mock.patch targets etc.).
        for target in _patch_string_module_targets(py_file, graph):
            if target != mod:
                graph.add_edge(mod, target)

    root_set = _gather_roots(root)
    for mod in root_set:
        if mod in graph:
            graph.nodes[mod]["is_root"] = True

    if granularity == "symbol":
        for py_file, mod in py_files:
            _enrich_symbol_layer(graph, py_file, mod)

    return graph


def roots(graph: nx.DiGraph) -> frozenset[str]:
    """Return the set of root/boundary module nodes tagged in the graph."""
    return frozenset(n for n, d in graph.nodes(data=True) if d.get("is_root"))


def reverse_deps(graph: nx.DiGraph, module: str) -> list[str]:
    """Return sorted list of modules that directly import module."""
    if module not in graph:
        return []
    return sorted(graph.predecessors(module))


def forward_closure(graph: nx.DiGraph, module: str) -> list[str]:
    """Return sorted list of all transitive imports of module (excluding itself)."""
    if module not in graph:
        return []
    return sorted(nx.descendants(graph, module))


def reachable_from_roots(graph: nx.DiGraph, module: str) -> bool:
    """True if module is reachable from any declared root node in the graph."""
    if module not in graph:
        return False
    root_set = roots(graph)
    if module in root_set:
        return True
    return any(r in graph and nx.has_path(graph, r, module) for r in root_set)


def to_export_dict(graph: nx.DiGraph) -> dict[str, Any]:
    """Return a deterministic JSON-serializable representation of the graph."""
    module_nodes = sorted(n for n, d in graph.nodes(data=True) if d.get("kind") == "module")
    symbol_nodes = sorted(n for n, d in graph.nodes(data=True) if d.get("kind") == "symbol")
    edges = [{"from": u, "to": v} for u, v in sorted(graph.edges())]
    return {
        "edges": edges,
        "metadata": {
            "generated_by": "scripts.dependency_graph",
            "known_unsound": KNOWN_UNSOUND,
        },
        "nodes": module_nodes,
        "roots": sorted(roots(graph)),
        "symbol_nodes": symbol_nodes,
    }


def check_export_freshness(failed: list[str], repo_root: Path | None = None) -> None:
    """No-op when no committed export exists; fails if the committed export drifts from current.

    Decision 80 lean posture: no file committed by default. Registered in the full
    presubmit tier only (Decision 73 non-wedging).
    repo_root defaults to _REPO_ROOT when None (normal validate.py invocation).
    """
    if not _EXPORT_PATH.exists():
        return
    try:
        committed = json.loads(_EXPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failed.append(f"Dependency graph freshness: cannot read committed export: {exc}")
        return
    current = to_export_dict(build_graph(repo_root=repo_root))
    if committed != current:
        try:
            path_display = _EXPORT_PATH.relative_to(_REPO_ROOT)
        except ValueError:
            path_display = _EXPORT_PATH
        failed.append(
            f"Dependency graph export {path_display} is stale. "
            "Re-run: bin/venv-python -m scripts.dependency_graph --export docs/dependency-graph.json"
        )


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="First-party import-graph oracle (ast + networkx). Decision 80.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--reverse-deps", metavar="MODULE", help="List modules that import MODULE.")
    parser.add_argument("--forward-closure", metavar="MODULE", help="List transitive imports of MODULE.")
    parser.add_argument("--reachable", metavar="MODULE", help="Report if MODULE is reachable from declared roots.")
    parser.add_argument(
        "--granularity",
        choices=["module", "symbol"],
        default="module",
        help="module (default) or symbol (adds function/class nodes and call edges).",
    )
    parser.add_argument("--export", metavar="PATH", help="Write graph JSON to PATH (deterministic).")
    parser.add_argument("--blind-spots", action="store_true", help="Print KNOWN_UNSOUND dynamic-dispatch blind spots.")
    args = parser.parse_args()

    if args.blind_spots:
        _print_json(KNOWN_UNSOUND)
        return

    graph = build_graph(granularity=args.granularity)

    if args.reverse_deps:
        _print_json(reverse_deps(graph, args.reverse_deps))
    elif args.forward_closure:
        _print_json(forward_closure(graph, args.forward_closure))
    elif args.reachable:
        _print_json({"module": args.reachable, "reachable": reachable_from_roots(graph, args.reachable)})
    elif args.export:
        export_path = Path(args.export)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(to_export_dict(graph), indent=2, sort_keys=True), encoding="utf-8")
        print(f"Graph exported to {export_path}", file=sys.stderr)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
