"""Unit tests for scripts/dependency_graph.py over a fixture module tree."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "dependency_graph.py"
_spec = importlib.util.spec_from_file_location("dependency_graph", _SCRIPT_PATH)
_dg = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_dg)  # type: ignore[union-attr]
sys.modules["dependency_graph"] = _dg

build_graph = _dg.build_graph
roots = _dg.roots
reverse_deps = _dg.reverse_deps
forward_closure = _dg.forward_closure
reachable_from_roots = _dg.reachable_from_roots
to_export_dict = _dg.to_export_dict
check_export_freshness = _dg.check_export_freshness
KNOWN_UNSOUND = _dg.KNOWN_UNSOUND
_file_to_module = _dg._file_to_module
_has_entry_point = _dg._has_entry_point
_gather_roots = _dg._gather_roots


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_fixture(tmp_path: Path) -> Path:
    """Create a minimal fixture module tree with known edges.

    Layout:
      src/__init__.py
      src/pkg/__init__.py
      src/pkg/module_a.py  -- imports scripts.helper (absolute)
      src/pkg/module_b.py  -- imports src.pkg.module_a via relative (from . import module_a)
      scripts/__init__.py
      scripts/helper.py    -- no first-party imports
      scripts/entrypoint.py -- def main(); imports scripts.helper
      tests/test_stuff.py  -- pytest test file (for root detection)
    """
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "module_a.py").write_text("from scripts.helper import do_stuff\n", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "module_b.py").write_text("from . import module_a\n", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "helper.py").write_text("def do_stuff():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "entrypoint.py").write_text(
        "from scripts.helper import do_stuff\n\ndef main():\n    do_stuff()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stuff.py").write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    return tmp_path


class TestBuildGraph:
    """Tests for build_graph() over the fixture tree."""

    def test_module_nodes_present(self, tmp_path: Path) -> None:
        """Nodes for all .py files in src/ scripts/ tests/ are present."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "src.pkg.module_a" in graph
        assert "src.pkg.module_b" in graph
        assert "scripts.helper" in graph
        assert "scripts.entrypoint" in graph
        assert "tests.test_stuff" in graph

    def test_absolute_import_edge(self, tmp_path: Path) -> None:
        """module_a -> scripts.helper edge from absolute 'from scripts.helper import ...'."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("src.pkg.module_a", "scripts.helper")

    def test_relative_import_edge(self, tmp_path: Path) -> None:
        """module_b -> src.pkg.module_a edge from relative 'from . import module_a'."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("src.pkg.module_b", "src.pkg.module_a")

    def test_scripts_star_edge(self, tmp_path: Path) -> None:
        """entrypoint -> scripts.helper edge from 'from scripts.helper import ...'."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert graph.has_edge("scripts.entrypoint", "scripts.helper")

    def test_no_self_edges(self, tmp_path: Path) -> None:
        """No module has an edge to itself."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        for u, v in graph.edges():
            assert u != v

    def test_kind_attribute(self, tmp_path: Path) -> None:
        """All nodes added by build_graph have kind='module' in module granularity."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        for n, data in graph.nodes(data=True):
            assert data.get("kind") == "module", f"{n} has kind={data.get('kind')!r}"


class TestRoots:
    """Tests for root set assembly."""

    def test_entrypoint_is_root(self, tmp_path: Path) -> None:
        """scripts.entrypoint has def main() -> is_root=True."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.entrypoint" in roots(graph)

    def test_test_file_is_root(self, tmp_path: Path) -> None:
        """tests/test_stuff.py is a root (pytest surface)."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "tests.test_stuff" in roots(graph)

    def test_helper_not_root(self, tmp_path: Path) -> None:
        """scripts.helper has no entry point -> not a root."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert "scripts.helper" not in roots(graph)


class TestReverseDeps:
    """Tests for reverse_deps()."""

    def test_reverse_deps_of_helper(self, tmp_path: Path) -> None:
        """Both module_a and entrypoint import helper."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        rdeps = reverse_deps(graph, "scripts.helper")
        assert "src.pkg.module_a" in rdeps
        assert "scripts.entrypoint" in rdeps
        assert rdeps == sorted(rdeps)

    def test_reverse_deps_of_unknown_module(self, tmp_path: Path) -> None:
        """Unknown module returns empty list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert reverse_deps(graph, "nonexistent.module") == []


class TestForwardClosure:
    """Tests for forward_closure()."""

    def test_forward_closure_of_entrypoint(self, tmp_path: Path) -> None:
        """entrypoint -> helper is in its forward closure."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        closure = forward_closure(graph, "scripts.entrypoint")
        assert "scripts.helper" in closure
        assert closure == sorted(closure)

    def test_forward_closure_of_module_b(self, tmp_path: Path) -> None:
        """module_b -> module_a -> helper: transitive closure includes helper."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        closure = forward_closure(graph, "src.pkg.module_b")
        assert "src.pkg.module_a" in closure
        assert "scripts.helper" in closure

    def test_forward_closure_of_leaf(self, tmp_path: Path) -> None:
        """Leaf node with no outgoing edges has empty closure."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert forward_closure(graph, "scripts.helper") == []

    def test_forward_closure_unknown(self, tmp_path: Path) -> None:
        """Unknown module returns empty list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert forward_closure(graph, "nonexistent") == []


class TestReachableFromRoots:
    """Tests for reachable_from_roots()."""

    def test_helper_reachable_via_entrypoint_root(self, tmp_path: Path) -> None:
        """scripts.helper is reachable because scripts.entrypoint (a root) imports it."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert reachable_from_roots(graph, "scripts.helper") is True

    def test_module_a_reachable_via_module_b_chain(self, tmp_path: Path) -> None:
        """src.pkg.module_a is reachable via module_b if module_b is reachable."""
        root = _make_fixture(tmp_path)
        (tmp_path / "scripts" / "caller.py").write_text(
            "from src.pkg import module_b\n\ndef main():\n    pass\n", encoding="utf-8"
        )
        graph = build_graph(repo_root=root)
        assert reachable_from_roots(graph, "scripts.caller") is True

    def test_root_itself_is_reachable(self, tmp_path: Path) -> None:
        """A root module is trivially reachable from the root set."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        root_set = roots(graph)
        for r in root_set:
            assert reachable_from_roots(graph, r) is True

    def test_unknown_module_not_reachable(self, tmp_path: Path) -> None:
        """A module not in the graph is not reachable."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        assert reachable_from_roots(graph, "nonexistent.module") is False


class TestExportDeterminism:
    """Tests for to_export_dict() determinism and structure."""

    def test_required_top_level_keys(self, tmp_path: Path) -> None:
        """Export dict has edges, metadata, nodes, roots, symbol_nodes keys."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert "edges" in exported
        assert "metadata" in exported
        assert "nodes" in exported
        assert "roots" in exported
        assert "symbol_nodes" in exported

    def test_known_unsound_in_export(self, tmp_path: Path) -> None:
        """Export metadata embeds the KNOWN_UNSOUND list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert "known_unsound" in exported["metadata"]
        assert exported["metadata"]["known_unsound"] is KNOWN_UNSOUND

    def test_nodes_sorted(self, tmp_path: Path) -> None:
        """nodes list is sorted."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert exported["nodes"] == sorted(exported["nodes"])

    def test_edges_sorted(self, tmp_path: Path) -> None:
        """edges list is sorted by (from, to)."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        edge_tuples = [(e["from"], e["to"]) for e in exported["edges"]]
        assert edge_tuples == sorted(edge_tuples)

    def test_json_byte_identical_across_runs(self, tmp_path: Path) -> None:
        """Two serializations of the same graph produce identical JSON bytes."""
        root = _make_fixture(tmp_path)
        graph1 = build_graph(repo_root=root)
        graph2 = build_graph(repo_root=root)
        j1 = json.dumps(to_export_dict(graph1), indent=2, sort_keys=True)
        j2 = json.dumps(to_export_dict(graph2), indent=2, sort_keys=True)
        assert j1 == j2

    def test_symbol_nodes_empty_in_module_granularity(self, tmp_path: Path) -> None:
        """symbol_nodes is empty when granularity is module (default)."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root)
        exported = to_export_dict(graph)
        assert exported["symbol_nodes"] == []


class TestSymbolGranularity:
    """Tests for symbol-level enrichment layer."""

    def test_symbol_nodes_added(self, tmp_path: Path) -> None:
        """Symbol granularity adds function/class nodes for top-level defs."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        symbol_nodes = [n for n, d in graph.nodes(data=True) if d.get("kind") == "symbol"]
        assert len(symbol_nodes) > 0

    def test_entrypoint_main_symbol_exists(self, tmp_path: Path) -> None:
        """scripts.entrypoint.main is a symbol node."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        assert "scripts.entrypoint.main" in graph

    def test_helper_do_stuff_symbol_exists(self, tmp_path: Path) -> None:
        """scripts.helper.do_stuff is a symbol node."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        assert "scripts.helper.do_stuff" in graph

    def test_export_symbol_nodes_populated(self, tmp_path: Path) -> None:
        """Export with symbol granularity populates symbol_nodes list."""
        root = _make_fixture(tmp_path)
        graph = build_graph(repo_root=root, granularity="symbol")
        exported = to_export_dict(graph)
        assert len(exported["symbol_nodes"]) > 0
        assert exported["symbol_nodes"] == sorted(exported["symbol_nodes"])


class TestKnownUnsound:
    """Tests for KNOWN_UNSOUND enumeration."""

    def test_known_unsound_has_four_entries(self) -> None:
        """KNOWN_UNSOUND enumerates exactly 4 blind spots."""
        assert len(KNOWN_UNSOUND) == 4

    def test_getattr_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert "getattr" in patterns

    def test_string_keyed_dispatch_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert "string-keyed dispatch" in patterns

    def test_importlib_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert "importlib.spec_from_file_location" in patterns

    def test_schedule_yaml_indirection_present(self) -> None:
        patterns = [e["pattern"] for e in KNOWN_UNSOUND]
        assert any("schedule.yaml" in p for p in patterns)


class TestCheckExportFreshness:
    """Tests for check_export_freshness()."""

    def test_no_op_when_no_committed_export(self, tmp_path: Path) -> None:
        """Freshness check is a no-op when docs/dependency-graph.json does not exist."""
        export_path = tmp_path / "docs" / "dependency-graph.json"
        with patch.object(_dg, "_EXPORT_PATH", export_path):
            failed: list[str] = []
            check_export_freshness(failed)
        assert not failed

    def test_fails_on_drift(self, tmp_path: Path) -> None:
        """Freshness check fails when committed export content differs from current graph."""
        export_path = tmp_path / "docs" / "dependency-graph.json"
        export_path.parent.mkdir(parents=True)
        stale_content = {"nodes": ["stale.module"], "edges": [], "roots": [], "metadata": {}, "symbol_nodes": []}
        export_path.write_text(json.dumps(stale_content), encoding="utf-8")
        with patch.object(_dg, "_EXPORT_PATH", export_path):
            failed: list[str] = []
            check_export_freshness(failed)
        assert len(failed) == 1
        assert "stale" in failed[0].lower() or "drift" in failed[0].lower() or "dependency graph" in failed[0].lower()

    def test_passes_when_export_matches_current(self, tmp_path: Path) -> None:
        """Freshness check passes when the committed export matches the current graph."""
        root = _make_fixture(tmp_path / "repo")
        export_path = tmp_path / "dependency-graph.json"
        with patch.object(_dg, "_REPO_ROOT", root), patch.object(_dg, "_EXPORT_PATH", export_path):
            graph = build_graph(repo_root=root)
            current = to_export_dict(graph)
            export_path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
            failed: list[str] = []
            check_export_freshness(failed)
        assert not failed
